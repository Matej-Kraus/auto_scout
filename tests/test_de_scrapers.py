"""Testy parseru DE scraperu (AutoScout24, Mobile.de) proti fixture — bez site."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.scrapers.autoscout24 import parse_listings
from app.scrapers.base import SearchQuery
from app.scrapers.mobilede_local import parse_listings as parse_mobilede

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_autoscout24_parses_and_filters_by_name():
    query = SearchQuery("audi_s3", "8p", {"name_includes": ["s3"]})
    out = parse_listings(_load("autoscout24_sample.json"), query)
    assert len(out) == 1  # A3 odfiltrovan podle name_includes
    r = out[0]
    assert r.source_id == "abc-123"
    assert r.price == 14900
    assert r.currency == "EUR"
    assert r.year == 2010
    assert r.mileage_km == 145000
    assert r.transmission_text == "Schaltgetriebe"
    assert r.image_url is not None
    assert r.url.startswith("https://www.autoscout24.de/")


def test_autoscout24_raises_on_broken_structure():
    query = SearchQuery("audi_s3", "8p", {})
    with pytest.raises(RuntimeError, match="listings"):
        parse_listings({"nope": 1}, query)


def test_mobilede_parses_real_snapshot():
    """Proti realnemu HTML snapshotu z mobile.de (ulozeno probe skriptem)."""
    html = (FIX / "mobilede_snapshot.html").read_text(encoding="utf-8")
    query = SearchQuery("golf_gti", "mk7", {"year_from": 2013, "year_to": 2020})
    out = parse_mobilede(html, query)
    assert len(out) >= 1
    r = out[0]
    assert r.source == "mobilede"
    assert r.currency == "EUR"
    assert r.price > 500
    assert r.year is not None and 2013 <= r.year <= 2020
    assert r.url.startswith("https://suchen.mobile.de/fahrzeuge/details.html?id=")
    assert r.image_url and r.image_url.startswith("https://img.classistatic.de/")


def test_mobilede_name_includes_filter():
    html = (FIX / "mobilede_snapshot.html").read_text(encoding="utf-8")
    # snapshot jsou Jetty → filtr na "golf" nesmi nic vratit
    query = SearchQuery("golf_gti", "mk7", {"name_includes": ["golf"]})
    assert parse_mobilede(html, query) == []


def test_mobilede_empty_html():
    query = SearchQuery("golf_gti", "mk7", {})
    assert parse_mobilede("<html><body>nic</body></html>", query) == []
