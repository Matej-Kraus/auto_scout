"""Mobile.de scraper — nejtvrdsi portal (Cloudflare), pres Playwright.

Z cloud IP (GitHub Actions) bude casto padat (CLAUDE.md §8) — to je ocekavane,
pipeline ho obali try/except a ostatni zdroje jedou dal. Lokalne / z residential
IP / self-hosted runneru funguje lip.

Playwright je volitelna zavislost (`pip install -e ".[playwright]"` + `playwright
install chromium`). Kdyz neni nainstalovany, scraper se proste preskoci.

Data Mobile.de tahá z embedded JSON v `window.__INITIAL_STATE__` na strance
vysledku. Parsing je oddeleny do `parse_initial_state()` kvuli testovatelnosti.
"""

from __future__ import annotations

import json
import logging

from app.scrapers.base import RawListing, Scraper, SearchQuery

logger = logging.getLogger(__name__)

BASE = "https://www.mobile.de"


class MobileDeScraper(Scraper):
    name = "mobilede"

    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        if not query.params:
            logger.info("mobilede[%s]: bez portal_params, preskakuji", query.model)
            return []
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("mobilede: Playwright nenainstalovan, preskakuji")
            return []

        url = _build_search_url(query)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="de-DE",
                )
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                state = page.evaluate("() => window.__INITIAL_STATE__ || null")
                if state is None:
                    # Cloudflare / captcha — padni hlasite, pipeline odchyti.
                    raise RuntimeError("mobilede: __INITIAL_STATE__ nenalezen (nejspis Cloudflare)")
            finally:
                browser.close()

        results = parse_initial_state(state, query)
        logger.info("mobilede[%s]: %d inzeratu", query.model, len(results))
        return results


def _build_search_url(query: SearchQuery) -> str:
    p = query.params
    parts = [f"{BASE}/fahrzeuge/search.html?isSearchRequest=true"]
    if p.get("make_model"):  # napr. "1900_24" (make_model id na mobile.de)
        parts.append(f"makeModelVariant1.makeId={p['make_model']}")
    if p.get("year_from"):
        parts.append(f"minFirstRegistrationDate={p['year_from']}-01-01")
    if p.get("year_to"):
        parts.append(f"maxFirstRegistrationDate={p['year_to']}-12-31")
    return "&".join(parts)


def parse_initial_state(state: dict | str, query: SearchQuery) -> list[RawListing]:
    """Z mobile.de __INITIAL_STATE__ vytahne RawListing. Testovatelne bez prohlizece."""
    if isinstance(state, str):
        state = json.loads(state)

    items = _find_items(state)
    if items is None:
        raise RuntimeError("mobilede: v __INITIAL_STATE__ nenalezen seznam inzeratu")

    name_includes = [s.lower() for s in query.params.get("name_includes", [])]
    out: list[RawListing] = []
    for item in items:
        title = item.get("title") or item.get("modelDescription") or ""
        low = title.lower()
        if name_includes and not all(n in low for n in name_includes):
            continue
        price = _int((item.get("price") or {}).get("gross") or item.get("priceRaw"))
        if not price:
            continue
        out.append(
            RawListing(
                source="mobilede",
                source_id=str(item.get("id")),
                title=title,
                url=_url(item),
                price=price,
                currency="EUR",
                year=_year(item),
                mileage_km=_int(item.get("mileage")),
                transmission_text=item.get("transmission") or item.get("gearbox"),
                drivetrain_text=title,
                raw=item,
            )
        )
    return out


def _find_items(state: dict) -> list | None:
    """Mobile.de mení strukturu — zkus nekolik znamych cest k seznamu inzeratu."""
    search = state.get("search") if isinstance(state, dict) else None
    if isinstance(search, dict):
        for key in ("srp", "results", "items"):
            node = search.get(key)
            if isinstance(node, dict) and isinstance(node.get("items"), list):
                return node["items"]
            if isinstance(node, list):
                return node
    if isinstance(state, dict) and isinstance(state.get("items"), list):
        return state["items"]
    return None


def _year(item: dict) -> int | None:
    raw = item.get("firstRegistration") or item.get("registrationDate")
    if not raw:
        return None
    digits = "".join(c for c in str(raw) if c.isdigit())
    for cand in (digits[-4:], digits[:4]):
        if len(cand) == 4 and cand.isdigit() and 1980 <= int(cand) <= 2100:
            return int(cand)
    return None


def _int(val) -> int | None:
    if val is None:
        return None
    digits = "".join(c for c in str(val) if c.isdigit())
    return int(digits) if digits else None


def _url(item: dict) -> str:
    url = item.get("relativeUrl") or item.get("url")
    if url:
        return url if url.startswith("http") else f"{BASE}{url}"
    return f"{BASE}/fahrzeuge/details.html?id={item.get('id', '')}"
