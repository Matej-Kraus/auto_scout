"""Test Sbazar scraperu proti syntetickemu JSON (zadna sit)."""

from __future__ import annotations

import httpx

from app.config import WATCHES
from app.scrapers.base import SearchQuery
from app.scrapers.sbazar import (
    SbazarScraper,
    _mileage_from_name,
    _year_from_name,
)


def _golf_watch():
    return next(w for w in WATCHES if w.model == "golf_gti")


_CAR_CAT = {"id": 153, "name": "Volkswagen"}

_SAMPLE = {
    "pagination": {"total": 5},
    "results": [
        {  # sedi: Mk7 s rokem i najezdem
            "id": 1,
            "name": "VW Golf VII 2.0 GTI, r.2016, 93804 km",
            "price": 380000,
            "category": _CAR_CAT,
            "images": [{"url": "//d46-a.sdn.cz/x/a.jpeg"}],
        },
        {  # spravne zahozen: stara generace bez roku (require_year)
            "id": 2,
            "name": "VW Golf I GTi veteran",
            "price": 250000,
            "category": _CAR_CAT,
            "images": [],
        },
        {  # zahozen: rok mimo rozsah (2008 < 2012)
            "id": 3,
            "name": "VW Golf V GTI 2008 super stav",
            "price": 200000,
            "category": _CAR_CAT,
            "images": [],
        },
        {  # zahozen: cena dohodou
            "id": 4,
            "name": "VW Golf GTI 2015",
            "price": 0,
            "price_by_agreement": True,
            "category": _CAR_CAT,
            "images": [],
        },
        {  # zahozen: nahradni dil, ne cele auto (kategorie)
            "id": 5,
            "name": "Naraznik VW Golf GTI 2016 predni 165000 km",
            "price": 380000,
            "category": {"id": 278, "name": "Části karoserie"},
            "images": [],
        },
    ],
}


def _client_from_sample() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        if offset == 0:
            return httpx.Response(200, json=_SAMPLE)
        return httpx.Response(200, json={"pagination": {"total": 5}, "results": []})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_filters_to_matching_mk7_only():
    scraper = SbazarScraper(client=_client_from_sample())
    results = scraper.fetch_listings(SearchQuery.from_watch(_golf_watch(), "sbazar"))

    assert len(results) == 1
    r = results[0]
    assert r.source == "sbazar"
    assert r.source_id == "1"
    assert r.year == 2016
    assert r.mileage_km == 93804
    assert r.price == 380000
    assert r.image_url == "https://d46-a.sdn.cz/x/a.jpeg"
    assert r.url == "https://www.sbazar.cz/inzerat/1"


def test_raises_on_broken_structure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    scraper = SbazarScraper(client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        scraper.fetch_listings(SearchQuery.from_watch(_golf_watch(), "sbazar"))
    except RuntimeError as exc:
        assert "results" in str(exc)
    else:
        raise AssertionError("ocekaval jsem RuntimeError pri rozbite strukture")


def test_year_parsing():
    assert _year_from_name("Golf GTI 2016 super") == 2016
    assert _year_from_name("Golf GTI Rv16") == 2016
    assert _year_from_name("Golf GTI bez roku") is None


def test_mileage_parsing():
    assert _mileage_from_name("najeto 136 tis km") == 136000
    assert _mileage_from_name("93804 km serviska") == 93804
    assert _mileage_from_name("125 000 km") == 125000
    assert _mileage_from_name("bez najezdu") is None
