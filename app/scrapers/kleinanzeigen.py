"""Kleinanzeigen.de scraper — nemecky bazar (ex-eBay Kleinanzeigen), ceny v EUR.

Nema JSON API, ale HTML vysledovka je stabilni a NENI za Cloudflare/Akamai
(overeno 7/2026 — na rozdil od mobile.de). Soukromi prodejci = casto nejlevnejsi
nemecke kusy, dobre doplnuje AutoScout24.

Server-side filtry primo v URL ceste:
  /s-autos/preis:{od}:{do}/{slug}/k0c216+autos.ez_i:{rok_od}%2C{rok_do}
Strankovani segmentem /seite:N/.

portal_params["kleinanzeigen"]:
  search_slug    — "volkswagen-golf-gti" (fulltext v ceste)
  name_includes  — substringy, ktere musi byt v titulku (client-side pojistka)
  year_from/to   — EZ filtr (server-side + client-side kontrola)
  price_from/to  — EUR (server-side)
"""

from __future__ import annotations

import html as html_mod
import logging
import random
import re
import time

import httpx

from app.config import settings
from app.scrapers.base import RawListing, Scraper, SearchQuery, title_matches

logger = logging.getLogger(__name__)

BASE = "https://www.kleinanzeigen.de"
CATEGORY = "k0c216"  # Autos
MAX_PAGES = 3  # 27 inzeratu/stranka, novejsi prvni
DELAY_RANGE = (3.0, 7.0)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

_ARTICLE_RE = re.compile(r'<article class="aditem"(.*?)</article>', re.S)
_ADID_RE = re.compile(r'data-adid="(\d+)"')
_HREF_RE = re.compile(r'data-href="([^"]+)"')
_TITLE_RE = re.compile(r'<a class="ellipsis"[^>]*>([^<]+)</a>')
_PRICE_RE = re.compile(r"aditem-main--middle--price[^>]*>\s*([\d.,]+)\s*€", re.S)
_TAG_RE = re.compile(r"simpletag[^>]*>([^<]+)<")
_IMG_RE = re.compile(r'<img[^>]+src="(https://img\.kleinanzeigen\.de[^"]+)"')
_EZ_RE = re.compile(r"EZ\s+(?:\d{2}/)?((?:19|20)\d{2})")
_KM_RE = re.compile(r"([\d.]+)\s*km", re.IGNORECASE)
_NO_RESULTS = "keine Anzeigen gefunden"
# Vykupove/poptavkove inzeraty a vraky — nejsou to nabidky jezdicich aut
# a jejich "ceny" by kazily scoring (S3 s motorschadenem za 5500 € = fake deal).
_JUNK_TITLE_RE = re.compile(
    r"\b(suche|gesucht|ankauf|kaufe|motorschaden|getriebeschaden|schlachtfest|ersatzteile)\b",
    re.IGNORECASE,
)


class KleinanzeigenScraper(Scraper):
    name = "kleinanzeigen"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers=_HEADERS, timeout=25.0, verify=settings.ssl_verify, follow_redirects=True
        )
        self._owns_client = client is None

    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        p = query.params
        if not p.get("search_slug"):
            logger.info("kleinanzeigen[%s]: bez search_slug, preskakuji", query.model)
            return []

        results: list[RawListing] = []
        for page in range(1, MAX_PAGES + 1):
            html = self._fetch_page(query, page)
            batch = parse_listings(html, query)
            results.extend(batch)
            if len(batch) < 25:  # posledni (nezaplnena) stranka
                break
            time.sleep(random.uniform(*DELAY_RANGE))

        logger.info("kleinanzeigen[%s]: %d inzeratu", query.model, len(results))
        return results

    def _fetch_page(self, query: SearchQuery, page: int) -> str:
        p = query.params
        segments = ["s-autos"]
        if page > 1:
            segments.append(f"seite:{page}")
        if p.get("price_from") or p.get("price_to"):
            segments.append(f"preis:{p.get('price_from') or ''}:{p.get('price_to') or ''}")
        segments.append(p["search_slug"])

        suffix = CATEGORY
        if p.get("year_from") or p.get("year_to"):
            suffix += f"+autos.ez_i:{p.get('year_from') or ''}%2C{p.get('year_to') or ''}"

        url = f"{BASE}/{'/'.join(segments)}/{suffix}"
        # S cookies Kleinanzeigen servíruje JS-hydrated variantu bez <article
        # class="aditem"> — bez cookies vraci vzdy parsovatelne staticke HTML.
        self._client.cookies.clear()
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.text

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def parse_listings(html: str, query: SearchQuery) -> list[RawListing]:
    """Z HTML vysledovky vytahne RawListing. Pri zmene struktury padne hlasite."""
    articles = _ARTICLE_RE.findall(html)
    if not articles:
        if _NO_RESULTS in html:
            return []  # legitimne prazdny vysledek
        raise RuntimeError(
            'Kleinanzeigen: zadny <article class="aditem"> — zmena struktury/blokace?'
        )

    params = query.params
    name_includes = params.get("name_includes", [])
    out: list[RawListing] = []

    for art in articles:
        adid = _ADID_RE.search(art)
        title_m = _TITLE_RE.search(art)
        price_m = _PRICE_RE.search(art)
        if not (adid and title_m and price_m):
            continue  # VB (cena dohodou) / promo bloky

        title = html_mod.unescape(title_m.group(1).strip())
        if not title_matches(title, name_includes):
            continue
        if _JUNK_TITLE_RE.search(title):
            continue  # vykup/poptavka/vrak

        price = int(re.sub(r"[^\d]", "", price_m.group(1)) or 0)
        if not price:
            continue

        tags = " · ".join(t.strip() for t in _TAG_RE.findall(art))
        year = _year_from_tags(tags)
        if year is not None:
            if params.get("year_from") and year < params["year_from"]:
                continue
            if params.get("year_to") and year > params["year_to"]:
                continue
        elif params.get("year_from") or params.get("year_to"):
            continue  # bez EZ nepozname generaci → zahodit (konzistentni s ostatnimi)

        href = _HREF_RE.search(art)
        img = _IMG_RE.search(art)
        out.append(
            RawListing(
                source="kleinanzeigen",
                source_id=adid.group(1),
                title=title,
                url=f"{BASE}{href.group(1)}" if href else f"{BASE}/s-anzeige/{adid.group(1)}",
                price=price,
                currency="EUR",
                year=year,
                mileage_km=_km_from_tags(tags),
                transmission_text=title,  # KA nema strukturovanou prevodovku ve vypisu
                drivetrain_text=title,
                fuel_text=title,
                image_url=img.group(1) if img else None,
                raw={"tags": tags},
            )
        )
    return out


def _year_from_tags(tags: str) -> int | None:
    m = _EZ_RE.search(tags)
    return int(m.group(1)) if m else None


def _km_from_tags(tags: str) -> int | None:
    m = _KM_RE.search(tags)
    if not m:
        return None
    val = int(re.sub(r"[^\d]", "", m.group(1)) or 0)
    return val if 1_000 <= val <= 1_000_000 else None
