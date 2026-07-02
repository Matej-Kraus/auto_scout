"""AutoScout24 scraper — pan-evropský portál (.de), ceny v EUR.

AS24 je Next.js app: výsledky hledání jsou v `<script id="__NEXT_DATA__">` jako JSON
(`props.pageProps.listings`). Žádné interní API ID — stačí slug v URL cestě
`/lst/{make}/{model}` (např. /lst/volkswagen/golf). Z běžné IP to jede; z cloud IP
(GitHub Actions) může občas padat na Cloudflare — pipeline to ustojí (CLAUDE.md §8).

Parsing je oddělený (`parse_listings`) kvůli testovatelnosti proti fixture.
Mapování v config.WATCHES → portal_params["autoscout24"]:
  make_slug, model_slug — cesta v URL (volkswagen, golf)
  name_includes         — substringy v názvu (client-side, kvůli motoru/výbavě)
  year_from/to          — fregfrom/fregto (server-side)
  price_to              — priceto (server-side, EUR)
"""

from __future__ import annotations

import json
import logging
import random
import re
import time

import httpx

from app.config import settings
from app.scrapers.base import RawListing, Scraper, SearchQuery

logger = logging.getLogger(__name__)

BASE = "https://www.autoscout24.de"
PER_PAGE = 20
MAX_PAGES = 5
DELAY_RANGE = (3.0, 8.0)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Referer": "https://www.autoscout24.de/",
}


class AutoScout24Scraper(Scraper):
    name = "autoscout24"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers=_HEADERS, timeout=30.0, verify=settings.ssl_verify, follow_redirects=True
        )
        self._owns_client = client is None

    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        p = query.params
        if not p.get("make_slug") or not p.get("model_slug"):
            logger.info("autoscout24[%s]: bez make_slug/model_slug, preskakuji", query.model)
            return []

        results: list[RawListing] = []
        for page in range(MAX_PAGES):
            page_props = self._fetch_page(query, page)
            batch = parse_listings(page_props, query)
            results.extend(batch)
            total_pages = page_props.get("numberOfPages") or 1
            if not batch or page + 1 >= total_pages:
                break
            time.sleep(random.uniform(*DELAY_RANGE))

        logger.info("autoscout24[%s]: %d inzeratu", query.model, len(results))
        return results

    def _fetch_page(self, query: SearchQuery, page: int) -> dict:
        p = query.params
        url = f"{BASE}/lst/{p['make_slug']}/{p['model_slug']}"
        params: dict = {"atype": "C", "sort": "age", "desc": 1, "page": page + 1}
        if p.get("year_from"):
            params["fregfrom"] = p["year_from"]
        if p.get("year_to"):
            params["fregto"] = p["year_to"]
        if p.get("price_to"):
            params["priceto"] = p["price_to"]
        if p.get("power_from_kw"):
            # Pro vzacne silne varianty (BMW 130i) — jinak je "od nejnovejsich"
            # nikdy nedosahne, protoze jsou stare a hluboko ve vysledcich.
            params["powertype"] = "kw"
            params["powerfrom"] = p["power_from_kw"]

        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return extract_page_props(resp.text)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def extract_page_props(html: str) -> dict:
    """Vytáhne props.pageProps z __NEXT_DATA__. Padne hlasitě při změně stránky."""
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise RuntimeError("AutoScout24: __NEXT_DATA__ nenalezen (Cloudflare/změna stránky?)")
    data = json.loads(m.group(1))
    return data.get("props", {}).get("pageProps", {})


def parse_listings(page_props: dict, query: SearchQuery) -> list[RawListing]:
    """Z pageProps.listings vytvoří RawListing. Padne hlasitě při změně struktury."""
    listings = page_props.get("listings")
    if listings is None:
        raise RuntimeError(
            f"AutoScout24: chybi klic 'listings', dostal {list(page_props)[:8]}"
        )

    name_includes = [s.lower() for s in query.params.get("name_includes", [])]
    out: list[RawListing] = []
    for item in listings:
        vehicle = item.get("vehicle") or {}
        title = _title(vehicle, item)
        low = title.lower()
        if name_includes and not all(n in low for n in name_includes):
            continue

        price = _int((item.get("price") or {}).get("priceRaw"))
        if not price:
            continue

        year = _year(item, vehicle)
        if year is None and (query.params.get("year_from") or query.params.get("year_to")):
            # Server-side freg filtr by mel rok zarucit; kdyz presto chybi,
            # radeji zahodit nez pustit neznamou generaci do scoringu.
            continue

        out.append(
            RawListing(
                source="autoscout24",
                source_id=str(item.get("id") or item.get("identifier")),
                title=title,
                url=_url(item),
                price=price,
                currency="EUR",
                year=year,
                mileage_km=_mileage(item),
                transmission_text=_gearbox(item),
                drivetrain_text=title,
                fuel_text=_detail_from_icons(item, "gas_pump"),
                image_url=_first_image(item),
                raw=item,
            )
        )
    return out


def _title(vehicle: dict, item: dict) -> str:
    parts = [vehicle.get("make"), vehicle.get("model"), vehicle.get("modelVersionInput")]
    title = " ".join(x for x in parts if x).strip()
    return title or item.get("title", "")


def _detail_from_icons(item: dict, icon: str) -> str | None:
    for d in item.get("vehicleDetails") or []:
        if d.get("iconName") == icon:
            return d.get("data")
    return None


def _mileage(item: dict) -> int | None:
    tr = item.get("tracking") or {}
    return _int(tr.get("mileage")) or _int(_detail_from_icons(item, "mileage_odometer"))


def _gearbox(item: dict) -> str | None:
    # "Automatik" / "Schaltgetriebe" — normalize.py si poradí
    return _detail_from_icons(item, "gearbox") or _detail_from_icons(item, "transmission")


def _year(item: dict, vehicle: dict) -> int | None:
    tr = item.get("tracking") or {}
    raw = tr.get("firstRegistration") or _detail_from_icons(item, "calendar")
    if not raw:
        return None
    # formát "05-2025" / "05/2025" / "2025"
    for cand in re.findall(r"\d{4}", str(raw)):
        if 1980 <= int(cand) <= 2100:
            return int(cand)
    return None


def _first_image(item: dict) -> str | None:
    images = item.get("images") or []
    if images and isinstance(images[0], str):
        return images[0]
    return None


def _int(val) -> int | None:
    if val is None:
        return None
    digits = "".join(c for c in str(val) if c.isdigit())
    return int(digits) if digits else None


def _url(item: dict) -> str:
    url = item.get("url")
    if url:
        return url if url.startswith("http") else f"{BASE}{url}"
    return f"{BASE}/offers/{item.get('id', '')}"
