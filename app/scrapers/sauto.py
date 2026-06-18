"""Sauto.cz scraper — interni JSON API (zadne parsovani HTML).

Server-side honorovane filtry: `manufacturer_model_seo` ("znacka:model"),
`price_from`/`price_to`, `tachometer_from`/`tachometer_to`. Rocnik a presnou
generaci/motor (130i, GTI) dofiltrujeme client-side podle nazvu, protoze Sauto
fulltext na tomhle endpointu nehonoruje.
"""

from __future__ import annotations

import logging
import random
import time

import httpx

from app.scrapers.base import RawListing, Scraper, SearchQuery

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.sauto.cz/api/v1/items/search"
CATEGORY_OSOBNI = 838
PER_PAGE = 100
MAX_PAGES = 25  # bezpecnostni strop; normalne se zastavi az projde celou sadu
DELAY_RANGE = (2.0, 5.0)  # slusny delay mezi requesty (JSON endpoint, lehky)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "cs,en;q=0.8",
    "Referer": "https://www.sauto.cz/",
}


class SautoScraper(Scraper):
    name = "sauto"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(headers=_HEADERS, timeout=20.0)
        self._owns_client = client is None

    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        results: list[RawListing] = []
        for page in range(MAX_PAGES):
            offset = page * PER_PAGE
            payload = self._fetch_page(query, offset)
            items = payload.get("results")
            if items is None:
                # Zmena struktury portalu — padni hlasite (CLAUDE.md §8).
                raise RuntimeError(
                    f"Sauto: ocekaval jsem klic 'results', dostal {list(payload)[:8]}"
                )
            if not items:
                break

            for item in items:
                raw = self._match_and_build(item, query)
                if raw is not None:
                    results.append(raw)

            total = (payload.get("pagination") or {}).get("total", 0)
            if offset + PER_PAGE >= total:
                break
            time.sleep(random.uniform(*DELAY_RANGE))

        logger.info("sauto[%s]: %d odpovidajicich inzeratu", query.model, len(results))
        return results

    def _fetch_page(self, query: SearchQuery, offset: int) -> dict:
        params: dict = {
            "category_id": CATEGORY_OSOBNI,
            "per_page": PER_PAGE,
            "offset": offset,
        }
        p = query.params
        if p.get("model_seo"):
            params["manufacturer_model_seo"] = p["model_seo"]
        for src, dst in (
            ("price_from", "price_from"),
            ("price_to", "price_to"),
            ("tachometer_from", "tachometer_from"),
            ("tachometer_to", "tachometer_to"),
        ):
            if p.get(src) is not None:
                params[dst] = p[src]

        resp = self._client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
        return resp.json()

    def _match_and_build(self, item: dict, query: SearchQuery) -> RawListing | None:
        """Client-side filtr (nazev + rocnik) + prevod na RawListing."""
        params = query.params
        name = (item.get("name") or "")
        low = name.lower()
        for needle in params.get("name_includes", []):
            if needle.lower() not in low:
                return None

        year = _year_from_date(item.get("manufacturing_date"))
        if year is not None:
            if params.get("year_from") and year < params["year_from"]:
                return None
            if params.get("year_to") and year > params["year_to"]:
                return None

        price = item.get("price")
        if not price:
            return None  # poptavka / cena dohodou — preskoc

        gearbox = (item.get("gearbox_cb") or {}).get("name")
        return RawListing(
            source=self.name,
            source_id=str(item["id"]),
            title=name,
            url=_detail_url(item),
            price=int(price),
            currency="CZK",
            year=year,
            mileage_km=item.get("tachometer"),
            transmission_text=gearbox,
            drivetrain_text=name,  # pohon Sauto v zakladu nedava → odvodi se z nazvu/modelu
            raw=item,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def _year_from_date(date_str: str | None) -> int | None:
    if not date_str or len(date_str) < 4:
        return None
    try:
        return int(date_str[:4])
    except ValueError:
        return None


def _detail_url(item: dict) -> str:
    man = (item.get("manufacturer_cb") or {}).get("seo_name", "auto")
    model = (item.get("model_cb") or {}).get("seo_name", "vuz")
    return f"https://www.sauto.cz/osobni/detail/{man}/{model}/{item['id']}"
