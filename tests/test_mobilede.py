"""Testy mobile.de scraperu — parser, filtry, mapovani ID, stavba URL.

Mobile.de meni markup casto (mezi dvema behy v 8/2026 dvakrat), proto parser
testujeme proti DVEMA fixturam ruznych variant. Zbytek (filtry, ID, razeni,
strankovani v URL) jsou ciste funkce bez site.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.scrapers.base import SearchQuery, title_matches
from app.scrapers.mobilede_local import (
    MAX_PAGES,
    _build_url,
    _extract_price_ratings,
    _resolve_ids,
    parse_listings,
)

FIX = Path(__file__).parent / "fixtures"
V1 = (FIX / "mobilede_snapshot.html").read_text(encoding="utf-8")  # stara varianta
V2 = (FIX / "mobilede_snapshot_v2.html").read_text(encoding="utf-8")  # nova varianta


def q(**params) -> SearchQuery:
    return SearchQuery("golf_gti", "mk7", params)


# --- parser: obe varianty markupu ---


def test_parses_new_markup_variant():
    out = parse_listings(V2, q())
    assert len(out) == 3
    first = next(r for r in out if r.source_id == "460000001")
    assert first.title == "Volkswagen Golf GTI Performance 2.0 TSI"
    assert first.price == 14_950
    assert first.currency == "EUR"
    assert first.year == 2016
    assert first.mileage_km == 94_787
    assert first.url == "https://suchen.mobile.de/fahrzeuge/details.html?id=460000001"
    assert first.image_url.startswith("https://img.classistatic.de/")


def test_parses_old_markup_variant():
    """Stary snapshot musi projit taky — parser ma byt nezavisly na variante."""
    out = parse_listings(V1, q(year_from=2013, year_to=2020))
    assert len(out) >= 1
    assert all(r.source == "mobilede" and r.price > 500 for r in out)


def test_empty_page_returns_nothing():
    assert parse_listings("<html><body>nic</body></html>", q()) == []


# --- hodnoceni ceny z JSON blobu ---


def test_price_rating_paired_by_listing_id():
    ratings = _extract_price_ratings(V2)
    assert ratings["460000001"] == "VERY_GOOD_PRICE"
    assert ratings["460000002"] == "HIGH_PRICE"
    assert "460000003" not in ratings  # tenhle inzerat hodnoceni nema


def test_price_rating_reaches_raw_listing():
    out = {r.source_id: r for r in parse_listings(V2, q())}
    assert out["460000001"].price_rating_text == "VERY_GOOD_PRICE"
    assert out["460000003"].price_rating_text is None


# --- filtry po stazeni (UI mobile.de je ma jen v modalu) ---


def test_transmission_filter_drops_automatics():
    out = parse_listings(V2, q(transmission="manual"))
    ids = {r.source_id for r in out}
    assert "460000002" not in ids  # "DSG Automatik" v nazvu
    assert "460000001" in ids


def test_power_filter_drops_weaker_engines():
    out = parse_listings(V2, q(power_from_kw=162))
    ids = {r.source_id for r in out}
    assert ids == {"460000001", "460000002"}  # GTD ma 135 kW → ven


def test_power_filter_drops_listings_without_known_power():
    """Neznamy vykon se NEPOUSTI — u overenych GTI se parsuje spolehlive,
    takze 'neznamo' skoro vzdy znamena zakladni verzi."""
    html = V2.replace("169&nbsp;kW&nbsp;(230&nbsp;PS)<!-- --> • <!-- -->Benzin", "Benzin")
    out = parse_listings(html, q(power_from_kw=162))
    assert "460000001" not in {r.source_id for r in out}


def test_fuel_filter_separates_petrol_and_diesel():
    petrol = {r.source_id for r in parse_listings(V2, q(fuel="petrol"))}
    diesel = {r.source_id for r in parse_listings(V2, q(fuel="diesel"))}
    assert petrol == {"460000001", "460000002"}
    assert diesel == {"460000003"}


def test_year_and_price_filters():
    assert {r.source_id for r in parse_listings(V2, q(year_from=2016))} == {"460000001"}
    assert "460000002" not in {r.source_id for r in parse_listings(V2, q(price_to=15_000))}


def test_name_includes_uses_word_boundaries():
    """'gti' nesmi chytit 'GTD' a naopak."""
    gti = {r.source_id for r in parse_listings(V2, q(name_includes=["gti"]))}
    gtd = {r.source_id for r in parse_listings(V2, q(name_includes=["gtd"]))}
    assert gti == {"460000001", "460000002"}
    assert gtd == {"460000003"}


# --- mapovani znacky/modelu na interni ID mobile.de ---


@pytest.mark.parametrize(
    "make,model,expected",
    [
        ("VW", "Golf", (25200, 14)),
        ("Volkswagen", "Golf", (25200, 14)),
        ("Škoda", "Octavia", (22900, 10)),  # diakritika se musi normalizovat
        ("SKODA", "octavia", (22900, 10)),
        ("BMW", "320i", (3500, 10)),  # motorizace se orizne: 320i -> 320
        ("BMW", "320d", (3500, 10)),
        ("BMW", "130i", (3500, 5)),
        ("AUDI", "S3", (1900, 19)),
        ("Ford", "Focus", None),  # nezname → fallback na fulltext
        ("VW", "Passat", None),
        (None, "Golf", None),
    ],
)
def test_resolve_ids(make, model, expected):
    assert _resolve_ids(make, model) == expected


# --- stavba URL ---


def test_url_uses_structured_ids_when_known():
    url = _build_url(q(make="VW", model="Golf", year_from=2013, year_to=2019, price_to=15_000))
    assert "makeModelVariant1.makeId=25200" in url
    assert "makeModelVariant1.modelId=14" in url
    assert "minFirstRegistrationDate=2013-01-01" in url
    assert "maxFirstRegistrationDate=2019-12-31" in url
    assert "maxPrice=15000" in url
    # fulltext se pri znamem ID nepouziva (mobile.de ho stejne zahazuje)
    assert "modelDescription" not in url


def test_url_falls_back_to_fulltext_for_unknown_model():
    url = _build_url(q(make="Ford", model="Focus", text="Ford Focus ST"))
    assert "modelDescription.modelDescription=Ford+Focus+ST" in url
    assert "makeModelVariant1" not in url


def test_url_sorts_by_price_when_filtering_narrow_trim():
    """Uzky trim v sirokem bucketu → razeni cenou, jinak by se ztratil.
    (Overeno na realu: Golf GTI 6 → 36 nalezenych po prepnuti razeni.)"""
    narrow = _build_url(q(make="VW", model="Golf", power_from_kw=162))
    assert "sb=p&od=down" in narrow

    broad = _build_url(q(make="VW", model="Golf"))
    assert "sb=doc&od=down" in broad  # jinak nejnovejsi


def test_pagination_capacity_is_reasonable():
    assert MAX_PAGES >= 5  # ~24 inzeratu/stranka → dost velky pool pred filtry


# --- sdilene word-boundary matchovani (pouzivaji vsechny scrapery) ---


@pytest.mark.parametrize(
    "title,needles,expected",
    [
        ("Audi S3 2.0 TFSI quattro", ["s3"], True),
        ("Audi a6 s3.0 polniche", ["s3"], False),  # objem motoru, ne model
        ("Opel Corsa F GS Line", ["rs"], False),  # 'rs' uvnitr 'Corsa'
        ("Skoda Octavia RS", ["rs"], True),
        ("BMW 130i M-Paket", ["130i"], True),
        ("BMW 120d", ["130i"], False),
        ("VW Golf GTI Performance", ["golf", "gti"], True),
        ("VW Golf GTD", ["golf", "gti"], False),
        ("cokoliv", [], True),  # bez pozadavku projde vse
        (None, ["gti"], False),
    ],
)
def test_title_matches(title, needles, expected):
    assert title_matches(title, needles) is expected
