"""Mobile.de scraper pro LOKÁLNÍ běh (rezidenční IP) přes Playwright Firefox.

Mobile.de chrání Akamai s behavioral challenge + reputací IP — z cloudu (GitHub
Actions) neprůchodné, z domácí IP Firefoxem to projde (ověřeno 7/2026, jeden
čistý průchod; Chromium je detekovaný vždy). Proto:

  - NEběží v hodinovém cronu; spouští ho `scripts/run_mobilede_local.py`
    (launchd na uživatelově Macu, 1× denně) a zapisuje do stejné DB.
  - Jeden požadavek na watch + dlouhé pauzy; při challenge měkce přeskočí
    (žádný failure alert — občasná blokace je očekávaný stav).

Parser je záměrně obecný (harvest z DOM přes odkazy na details.html), protože
markup se mění a JSON zdroj (__INITIAL_STATE__) už neexistuje.

portal_params["mobilede"] (volitelné; jinak se odvodí z watch labelu):
  text        — fulltext do modelDescription.modelDescription
  year_from/to, price_to (EUR)
"""

from __future__ import annotations

import logging
import random
import re
import time

from app.scrapers.base import RawListing, Scraper, SearchQuery

logger = logging.getLogger(__name__)

BASE = "https://suchen.mobile.de"
DELAY_RANGE = (25.0, 60.0)  # dlouhe pauzy mezi watchi — 1x denne nespechame

_PRICE_RE = re.compile(r"([\d.\s]{3,})\s*€")
_KM_RE = re.compile(r"([\d.\s]{2,})\s*km", re.IGNORECASE)
_EZ_RE = re.compile(r"EZ\s*(?:\d{2}/)?((?:19|20)\d{2})")
_ID_RE = re.compile(r"id=(\d+)")


class MobileDeLocalScraper(Scraper):
    """Playwright Firefox; jeden pokus na watch, měkké selhání při challenge."""

    name = "mobilede"

    def __init__(self) -> None:
        self._challenged = False  # po prvni challenge uz dalsi watche nezkousej

    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        if self._challenged:
            logger.info("mobilede[%s]: preskakuji (IP challenge v tomto behu)", query.model)
            return []
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("mobilede: Playwright neni nainstalovany, preskakuji")
            return []

        url = _build_url(query)
        with sync_playwright() as pw:
            browser = pw.firefox.launch(headless=True)
            ctx = browser.new_context(locale="de-DE", viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(8000)
                title = page.title()
                if "verweigert" in title.lower() or "denied" in title.lower() or not title:
                    # Akamai challenge — mekky skip, zadny alert (obcasny stav).
                    logger.warning("mobilede[%s]: Akamai challenge, preskakuji", query.model)
                    self._challenged = True
                    return []
                items = _harvest(page)
            finally:
                browser.close()

        raws = [_to_raw(it, query) for it in items]
        raws = [r for r in raws if r is not None]
        logger.info("mobilede[%s]: %d inzeratu", query.model, len(raws))
        time.sleep(random.uniform(*DELAY_RANGE))
        return raws


def _build_url(query: SearchQuery) -> str:
    p = query.params
    parts = [
        f"{BASE}/fahrzeuge/search.html?isSearchRequest=true&scopeId=C&usage=USED&sortOption.sortBy=creationTime&sortOption.sortOrder=DESCENDING"
    ]
    text = p.get("text")
    if text:
        parts.append("modelDescription.modelDescription=" + text.replace(" ", "+"))
    if p.get("year_from"):
        parts.append(f"minFirstRegistrationDate={p['year_from']}-01-01")
    if p.get("year_to"):
        parts.append(f"maxFirstRegistrationDate={p['year_to']}-12-31")
    if p.get("price_to"):
        parts.append(f"maxPrice={p['price_to']}")
    return "&".join(parts)


def _harvest(page) -> list[dict]:
    """Obecný sběr výsledků: najdi odkazy na details.html a vytáhni okolní data."""
    return page.evaluate(
        """() => {
        const seen = new Set();
        const out = [];
        for (const a of document.querySelectorAll('a[href*="details.html"]')) {
            const href = a.href;
            if (seen.has(href)) continue;
            seen.add(href);
            // vyjed nahoru na kontejner vysledku (max 6 urovni)
            let node = a;
            for (let i = 0; i < 6 && node.parentElement; i++) {
                node = node.parentElement;
                if ((node.innerText || '').includes('€')) break;
            }
            const img = node.querySelector('img[src*="mobile.de"], img[src^="https"]');
            out.push({
                href,
                text: (node.innerText || '').slice(0, 600),
                img: img ? img.src : null,
            });
        }
        return out;
    }"""
    )


def _to_raw(item: dict, query: SearchQuery) -> RawListing | None:
    text = item.get("text") or ""
    href = item.get("href") or ""
    m_id = _ID_RE.search(href)
    if not m_id:
        return None

    m_price = _PRICE_RE.search(text)
    if not m_price:
        return None
    price = int(re.sub(r"[^\d]", "", m_price.group(1)) or 0)
    if price < 500:  # sponzorovane bloky/reklamy
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = lines[0][:200] if lines else "mobile.de inzerat"
    low = title.lower()
    params = query.params
    for needle in params.get("name_includes", []):
        if needle.lower() not in low:
            return None

    m_year = _EZ_RE.search(text)
    year = int(m_year.group(1)) if m_year else None
    if year is not None:
        if params.get("year_from") and year < params["year_from"]:
            return None
        if params.get("year_to") and year > params["year_to"]:
            return None
    elif params.get("year_from") or params.get("year_to"):
        return None

    m_km = _KM_RE.search(text)
    km = int(re.sub(r"[^\d]", "", m_km.group(1)) or 0) if m_km else None
    if km is not None and not (1_000 <= km <= 1_000_000):
        km = None

    return RawListing(
        source="mobilede",
        source_id=m_id.group(1),
        title=title,
        url=href.split("?")[0] + f"?id={m_id.group(1)}",
        price=price,
        currency="EUR",
        year=year,
        mileage_km=km,
        transmission_text=text[:300],
        drivetrain_text=title,
        fuel_text=text[:300],
        image_url=item.get("img"),
        raw={"text": text[:400]},
    )
