"""Sbazar.cz scraper — interní JSON API (Seznam, stejná rodina jako Sauto).

Endpoint `/api/v1/items/search` honoruje fulltext přes parametr `phrase`.
Sbazar je obecný bazar: inzeráty nemají strukturovaný rok/nájezd/převodovku —
všechno je ve volném textu `name`, takže rok/km dofiltrujeme/odhadneme z názvu
a cenu honorujeme client-side. Pád při změně struktury je hlasitý (CLAUDE.md §8).

portal_params["sbazar"]:
  phrase         — fulltextový dotaz (server-side), např. "golf gti"
  name_includes  — všechny tyto substringy musí být v názvu (client-side)
  year_from/to   — ročníkový filtr (client-side, jen když rok z názvu vyčteme)
  price_from/to  — cenový filtr (client-side, cena je strukturovaná)
"""

from __future__ import annotations

import logging
import random
import re
import time

import httpx

from app.config import settings
from app.scrapers.base import RawListing, Scraper, SearchQuery

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.sbazar.cz/api/v1/items/search"
PER_PAGE = 100
MAX_PAGES = 6  # phrase uz vyrazne zuzi; nehltej cely bazar
DELAY_RANGE = (2.0, 5.0)
# Pojistka proti spatne zarazenym nahradnim dilum: cele pojizdne auto na Sbazaru
# nestoji 300 Kc. Plati jen kdyz watch nema vlastni price_from.
DEFAULT_MIN_PRICE_CZK = 30_000

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "cs,en;q=0.8",
    "Referer": "https://www.sbazar.cz/",
}

# Sbazar je obecny bazar — fulltext vraci i nahradni dily, kola, naraznik…
# Cela auta jsou v kategorii znacky ("Škoda", "BMW") nebo v obecnych auto
# kategoriich. Vse ostatni (dily, karoserie, bourana auta) zahazujeme.
_CAR_CATEGORY_NAMES = {"do 3,5 t", "ostatni auta", "osobni vozy", "veterani"}


def _fold(text: str) -> str:
    import unicodedata

    norm = unicodedata.normalize("NFKD", text)
    return norm.encode("ascii", "ignore").decode("ascii").lower().strip()


def _is_whole_car(item: dict, make_hint: str | None) -> bool:
    name = _fold((item.get("category") or {}).get("name") or "")
    if not name:
        return False
    if name in _CAR_CATEGORY_NAMES:
        return True
    if make_hint and name == _fold(make_hint):
        return True  # kategorie pojmenovana po znacce = cele vozy te znacky
    return False


# "136 tis. km" / "136 tisíc km" → 136000
_MILEAGE_TIS = re.compile(r"(\d{1,3})\s*tis", re.IGNORECASE)
# "najeto 93804 km" / "93 804 km" / "120000km" → cele cislo pred "km"
_MILEAGE_KM = re.compile(r"(\d[\d\s.]{2,})\s*km", re.IGNORECASE)


class SbazarScraper(Scraper):
    name = "sbazar"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers=_HEADERS, timeout=20.0, verify=settings.ssl_verify
        )
        self._owns_client = client is None

    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        phrase = query.params.get("phrase")
        if not phrase:
            return []  # bez fulltextu nemá smysl tahat cely bazar

        results: list[RawListing] = []
        for page in range(MAX_PAGES):
            offset = page * PER_PAGE
            payload = self._fetch_page(phrase, offset)
            items = payload.get("results")
            if items is None:
                raise RuntimeError(
                    f"Sbazar: ocekaval jsem klic 'results', dostal {list(payload)[:8]}"
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

        logger.info("sbazar[%s]: %d odpovidajicich inzeratu", query.model, len(results))
        return results

    def _fetch_page(self, phrase: str, offset: int) -> dict:
        params = {"phrase": phrase, "per_page": PER_PAGE, "offset": offset}
        resp = self._client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
        return resp.json()

    def _match_and_build(self, item: dict, query: SearchQuery) -> RawListing | None:
        params = query.params
        if not _is_whole_car(item, params.get("make")):
            return None  # nahradni dil / prislusenstvi, ne cele auto
        name = item.get("name") or ""
        low = name.lower()
        for needle in params.get("name_includes", []):
            if needle.lower() not in low:
                return None

        price = item.get("price")
        if not price or item.get("price_by_agreement"):
            return None  # cena dohodou / poptavka
        min_price = params.get("price_from") or DEFAULT_MIN_PRICE_CZK
        if price < min_price:
            return None
        if params.get("price_to") and price > params["price_to"]:
            return None

        year = _year_from_name(name)
        if year is not None:
            if params.get("year_from") and year < params["year_from"]:
                return None
            if params.get("year_to") and year > params["year_to"]:
                return None
        elif params.get("require_year") and (params.get("year_from") or params.get("year_to")):
            # Sbazar je volnotextovy: bez roku nepoznam generaci → radeji zahodit,
            # at se do scoring datasetu nepletou jine generace (Mk1/Mk2 Golf apod.).
            return None

        return RawListing(
            source=self.name,
            source_id=str(item["id"]),
            title=name,
            url=f"https://www.sbazar.cz/inzerat/{item['id']}",
            price=int(price),
            currency="CZK",
            year=year,
            mileage_km=_mileage_from_name(name),
            transmission_text=name,  # převodovka jen z názvu (často chybí)
            drivetrain_text=name,
            image_url=_first_image(item),
            raw=item,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def _year_from_name(name: str) -> int | None:
    """Rok z volného textu: '... 2016 ...' nebo 'Rv16' / 'r.v. 2016'."""
    m = re.search(r"(19[89]\d|20[0-3]\d)", name)
    if m:
        return int(m.group(0))
    m = re.search(r"\bRv\.?\s?(\d{2})\b", name, re.IGNORECASE)
    if m:
        return 2000 + int(m.group(1))
    return None


def _mileage_from_name(name: str) -> int | None:
    """Nájezd z volného textu. '136 tis km' → 136000; jinak nech None (raději nic
    než špatně — scoring si poradí i bez km)."""
    m = _MILEAGE_TIS.search(name)
    if m:
        return int(m.group(1)) * 1000
    m = _MILEAGE_KM.search(name)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        if digits:
            val = int(digits)
            if 1_000 <= val <= 1_000_000:  # rozumny rozsah najezdu
                return val
    return None


def _first_image(item: dict) -> str | None:
    images = item.get("images") or []
    if not images:
        return None
    url = (images[0] or {}).get("url")
    if not url:
        return None
    return "https:" + url if url.startswith("//") else url
