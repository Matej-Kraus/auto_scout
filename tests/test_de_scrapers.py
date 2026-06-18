"""Testy parseru DE scraperu (AutoScout24, Mobile.de) proti fixture — bez site."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.scrapers.autoscout24 import parse_listings
from app.scrapers.base import SearchQuery
from app.scrapers.mobilede import parse_initial_state

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
    assert r.transmission_text == "Manual"
    assert r.url.startswith("https://www.autoscout24.cz/")


def test_autoscout24_raises_on_broken_structure():
    query = SearchQuery("audi_s3", "8p", {})
    with pytest.raises(RuntimeError, match="listings"):
        parse_listings({"nope": 1}, query)


def test_mobilede_parses_and_filters():
    query = SearchQuery("bmw_130i", "e87", {"name_includes": ["130i"]})
    out = parse_initial_state(_load("mobilede_state.json"), query)
    assert len(out) == 1  # 118d odfiltrovan
    r = out[0]
    assert r.source_id == "900111"
    assert r.price == 11900
    assert r.currency == "EUR"
    assert r.year == 2008
    assert r.mileage_km == 138000
    assert "900111" in r.url


def test_mobilede_accepts_json_string():
    query = SearchQuery("bmw_130i", "e87", {"name_includes": ["130i"]})
    raw = (FIX / "mobilede_state.json").read_text(encoding="utf-8")
    out = parse_initial_state(raw, query)
    assert len(out) == 1


def test_mobilede_raises_on_broken_structure():
    query = SearchQuery("bmw_130i", "e87", {})
    with pytest.raises(RuntimeError):
        parse_initial_state({"search": {}}, query)
