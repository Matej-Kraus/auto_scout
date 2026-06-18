"""AutoScout24 scraper — DE/EU portal, ceny v EUR.

AutoScout24 servíruje vysledky pres interni JSON API (Next.js data layer).
Endpoint je chraneny (Cloudflare), takze z cloud IP (GitHub Actions) muze
obcas padat — pipeline to ustoji (try/except per scraper, CLAUDE.md §8).

Parsing je oddeleny do `parse_listings()`, aby sel testovat proti fixture
bez site. Mapovani znacky/modelu na AS24 interni ID je v config.WATCHES
(portal_params["autoscout24"]).
"""

from __future__ import annotations

import logging
import random
import time

import httpx

from app.config import settings
from app.scrapers.base import RawListing, Scraper, SearchQuery

logger = logging.getLogger(__name__)

# Interni list API AutoScout24 (vraci JSON se seznamem listingu).
SEARCH_URL = "https://www.autoscout24.cz/as24-search-funnel/api/v1/search/results"
PER_PAGE = 20
MAX_PAGES = 5
DELAY_RANGE = (3.0, 8.0)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "cs,en;q=0.8",
    "Referer": "https://www.autoscout24.cz/",
}


class AutoScout24Scraper(Scraper):
    name = "autoscout24"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers=_HEADERS, timeout=25.0, verify=settings.ssl_verify
        )
        self._owns_client = client is None

    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        if not query.params:
            logger.info("autoscout24[%s]: bez portal_params, preskakuji", query.model)
            return []

        results: list[RawListing] = []
        for page in range(MAX_PAGES):
            payload = self._fetch_page(query, page)
            batch = parse_listings(payload, query)
            results.extend(batch)
            if len(batch) < PER_PAGE:
                break
            time.sleep(random.uniform(*DELAY_RANGE))

        logger.info("autoscout24[%s]: %d inzeratu", query.model, len(results))
        return results

    def _fetch_page(self, query: SearchQuery, page: int) -> dict:
        p = query.params
        params = {
            "make": p.get("make"),
            "model": p.get("model"),
            "atype": "C",
            "sort": "age",
            "desc": 1,
            "ustate": "N,U",
            "size": PER_PAGE,
            "page": page,
        }
        if p.get("year_from"):
            params["fregfrom"] = p["year_from"]
        if p.get("year_to"):
            params["fregto"] = p["year_to"]
        resp = self._client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def parse_listings(payload: dict, query: SearchQuery) -> list[RawListing]:
    """Z JSON odpovedi AS24 vytahne RawListing. Padne hlasite pri zmene struktury."""
    listings = payload.get("listings")
    if listings is None:
        raise RuntimeError(
            f"AutoScout24: chybi klic 'listings', dostal {list(payload)[:8]}"
        )

    out: list[RawListing] = []
    name_includes = [s.lower() for s in query.params.get("name_includes", [])]

    for item in listings:
        vehicle = item.get("vehicle") or {}
        price_obj = item.get("price") or item.get("tracking") or {}
        price = _extract_price(price_obj, item)
        if not price:
            continue

        title = " ".join(
            x for x in (vehicle.get("make"), vehicle.get("model"), vehicle.get("modelVersionInput")) if x
        ).strip() or item.get("title", "")

        low = title.lower()
        if name_includes and not all(n in low for n in name_includes):
            continue

        out.append(
            RawListing(
                source="autoscout24",
                source_id=str(item.get("id") or item.get("guid")),
                title=title,
                url=_build_url(item),
                price=price,
                currency="EUR",
                year=_year(vehicle),
                mileage_km=_int(vehicle.get("mileageInKmRaw") or vehicle.get("mileage")),
                transmission_text=vehicle.get("transmissionType") or vehicle.get("transmission"),
                drivetrain_text=title,
                raw=item,
            )
        )
    return out


def _extract_price(price_obj: dict, item: dict) -> int | None:
    for key in ("priceRaw", "public", "amount", "price"):
        val = price_obj.get(key) if isinstance(price_obj, dict) else None
        if val:
            return _int(val)
    return _int(item.get("priceRaw"))


def _year(vehicle: dict) -> int | None:
    raw = vehicle.get("firstRegistrationDateRaw") or vehicle.get("firstRegistration")
    if not raw:
        return None
    digits = "".join(c for c in str(raw) if c.isdigit())
    # format byva MM-YYYY nebo YYYYMMDD nebo YYYY
    if len(digits) >= 4:
        # zkus posledni 4 (MM-YYYY) i prvni 4 (YYYY...)
        for cand in (digits[-4:], digits[:4]):
            if cand.isdigit() and 1980 <= int(cand) <= 2100:
                return int(cand)
    return None


def _int(val) -> int | None:
    if val is None:
        return None
    digits = "".join(c for c in str(val) if c.isdigit())
    return int(digits) if digits else None


def _build_url(item: dict) -> str:
    url = item.get("url")
    if url:
        return url if url.startswith("http") else f"https://www.autoscout24.cz{url}"
    return f"https://www.autoscout24.cz/inzerat/{item.get('id', '')}"
