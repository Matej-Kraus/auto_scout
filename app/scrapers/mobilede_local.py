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

import html as html_mod
import logging
import random
import re
import time

from app.scrapers.base import RawListing, Scraper, SearchQuery

logger = logging.getLogger(__name__)

BASE = "https://suchen.mobile.de"
# mobile.de/Akamai pusti z rezidencni IP ~1 pozadavek, pak IP na chvili flagne.
# Proto: JEDEN pokus na watch (retry jen flag prodluzuje) + dlouha pauza mezi watchi,
# aby se stihla reputace srovnat. Po prvni challenge uz dalsi watche nezkousime.
DELAY_RANGE = (60.0, 120.0)

# Vysledovka mobile.de je Next.js — jeden inzerat zacina data-testid
# "listing-title-card-view". V bloku pak: cena (price-label), atributy
# (EZ MM/RRRR • km • kW • palivo), obrazek (img.classistatic.de), odkaz details.html.
_BLOCK_SPLIT = re.compile(r'(?=data-testid="listing-title-card-view")')
# Nazev = hlavni ("Volkswagen Golf") + podtitul z title="..." atributu
# ("GTI 2.0 TSI DSG"). Podtitul nese motorizaci → klicovy pro name_includes.
_TITLE_RE = re.compile(r'data-testid="listing-title-card-view"[^>]*>(.*?)</span>', re.S)
_SUBTITLE_RE = re.compile(r'class="ListingTitle-module__[^"]*subTitle"[^>]*title="([^"]*)"')
_PRICE_RE = re.compile(r'data-testid="price-label"[^>]*>(.*?)</span>', re.S)
_ATTR_RE = re.compile(
    r'data-testid="listing-details-attributes"[^>]*>(.*?)'
    r'(?=data-testid="seller-info"|data-testid="listing-action)',
    re.S,
)
_HREF_RE = re.compile(r'href="([^"]*details\.html[^"]*)"')
_IMG_RE = re.compile(r'src="(https://img\.classistatic\.de/[^"\s]+)"')
_ID_RE = re.compile(r"[?&]id=(\d+)")
_EZ_RE = re.compile(r"EZ\s*(?:\d{2}/)?((?:19|20)\d{2})")
_KM_RE = re.compile(r"([\d.]{2,})\s*km", re.IGNORECASE)


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
        page_html: str | None = None
        with sync_playwright() as pw:
            # Cerstvy Firefox + novy kontext (presne jako funkcni probe). JEDEN pokus.
            browser = pw.firefox.launch(headless=True)
            try:
                ctx = browser.new_context(locale="de-DE", viewport={"width": 1440, "height": 900})
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(8000)  # nech Akamai JS dobehnout
                title = page.title()
                if title and "verweigert" not in title.lower() and "denied" not in title.lower():
                    page_html = page.content()
            finally:
                browser.close()

        if page_html is None:
            logger.warning("mobilede[%s]: Akamai challenge, preskakuji (IP potrebuje klid)", query.model)
            self._challenged = True
            return []

        raws = parse_listings(page_html, query)
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


def _clean(fragment: str) -> str:
    """HTML fragment → čistý text (bez tagů, dekódované entity, sjednocené mezery)."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_mod.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_listings(page_html: str, query: SearchQuery) -> list[RawListing]:
    """Rozparsuje HTML výsledovky mobile.de na RawListing. Testovatelné bez sítě."""
    blocks = _BLOCK_SPLIT.split(page_html)
    params = query.params
    name_includes = [s.lower() for s in params.get("name_includes", [])]
    out: list[RawListing] = []
    seen: set[str] = set()

    for blk in blocks:
        title_m = _TITLE_RE.search(blk)
        price_m = _PRICE_RE.search(blk)
        href_m = _HREF_RE.search(blk)
        if not (title_m and price_m and href_m):
            continue

        href = html_mod.unescape(href_m.group(1))
        id_m = _ID_RE.search(href)
        if not id_m or id_m.group(1) in seen:
            continue
        source_id = id_m.group(1)

        title = _clean(title_m.group(1))
        sub_m = _SUBTITLE_RE.search(blk)
        if sub_m:
            title = f"{title} {html_mod.unescape(sub_m.group(1))}".strip()
        low = title.lower()
        if name_includes and not all(n in low for n in name_includes):
            continue

        price = int(re.sub(r"[^\d]", "", _clean(price_m.group(1))) or 0)
        if price < 500:  # sponzorovaný blok / bez ceny
            continue

        attrs_m = _ATTR_RE.search(blk)
        attrs = _clean(attrs_m.group(1)) if attrs_m else ""

        year = None
        ez = _EZ_RE.search(attrs)
        if ez:
            year = int(ez.group(1))
        if year is not None:
            if params.get("year_from") and year < params["year_from"]:
                continue
            if params.get("year_to") and year > params["year_to"]:
                continue
        elif params.get("year_from") or params.get("year_to"):
            continue

        km = None
        km_m = _KM_RE.search(attrs)
        if km_m:
            val = int(re.sub(r"[^\d]", "", km_m.group(1)) or 0)
            if 1_000 <= val <= 1_000_000:
                km = val

        img_m = _IMG_RE.search(blk)
        seen.add(source_id)
        out.append(
            RawListing(
                source="mobilede",
                source_id=source_id,
                title=title,
                url=f"{BASE}/fahrzeuge/details.html?id={source_id}",
                price=price,
                currency="EUR",
                year=year,
                mileage_km=km,
                transmission_text=attrs,  # normalize vytáhne manual/automat
                drivetrain_text=title,
                fuel_text=attrs,  # Benzin/Diesel je v atributech
                power_text=attrs,  # "92 kW (125 PS)" je v atributech
                body_text=title,
                image_url=img_m.group(1) if img_m else None,
                raw={"attrs": attrs},
            )
        )
    return out
