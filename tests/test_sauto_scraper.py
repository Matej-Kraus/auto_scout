"""Test Sauto scraperu proti ulozenemu JSON sample (zadna sit)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.config import WATCHES
from app.scrapers.base import SearchQuery
from app.scrapers.sauto import SautoScraper

FIXTURE = Path(__file__).parent / "fixtures" / "sauto_sample.json"


def _client_from_fixture() -> httpx.Client:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        if offset == 0:
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"pagination": {"total": 3}, "results": []})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _bmw_watch():
    return next(w for w in WATCHES if w.model == "bmw_130i")


def test_filters_to_matching_only():
    scraper = SautoScraper(client=_client_from_fixture())
    query = SearchQuery.from_watch(_bmw_watch(), "sauto")
    results = scraper.fetch_listings(query)

    # Z fixtures sedi jen 130i (Ford padne na znacku, 116i na frazi '130i')
    assert len(results) == 1
    r = results[0]
    assert r.source_id == "210453992"
    assert r.price == 215000
    assert r.currency == "CZK"
    assert r.year == 2011
    assert r.mileage_km == 140000
    assert r.transmission_text == "Manuální"
    assert "210453992" in r.url


def test_raises_on_broken_structure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    scraper = SautoScraper(client=httpx.Client(transport=httpx.MockTransport(handler)))
    query = SearchQuery.from_watch(_bmw_watch(), "sauto")
    try:
        scraper.fetch_listings(query)
    except RuntimeError as exc:
        assert "results" in str(exc)
    else:
        raise AssertionError("ocekaval jsem RuntimeError pri rozbite strukture")
