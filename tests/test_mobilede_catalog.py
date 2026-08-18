"""Testy katalogu ID mobile.de — normalizace klicu a vyhledavani.

Sitova cast (resolve_missing_makes) se netestuje, tady jde o cistou logiku
prekladu jmen na klice, ktera je zdrojem tichych chyb: spatny klic = mobile.de
vrati nesouvisejici auta misto chyby.
"""

from __future__ import annotations

import pytest

from app.mobilede_catalog import make_key, model_key, resolve_ids

CATALOG = {
    "makes": {"VW": 25200, "BMW": 3500, "AUDI": 1900, "SKODA": 22900, "FORD": 9000},
    "models": {
        "VW:GOLF": 14,
        "BMW:130": 5,
        "BMW:320": 10,
        "AUDI:S3": 19,
        "SKODA:OCTAVIA": 10,
        "FORD:FOCUS": 20,
    },
}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("VW", "VW"),
        ("Volkswagen", "VW"),  # alias
        ("volkswagen", "VW"),
        ("Škoda", "SKODA"),  # diakritika
        ("ŠKODA", "SKODA"),
        ("  bmw  ", "BMW"),  # mezery
        ("Mercedes", "MERCEDES-BENZ"),
    ],
)
def test_make_key_normalisation(raw, expected):
    assert make_key(raw) == expected


@pytest.mark.parametrize(
    "make,model,expected",
    [
        ("BMW", "320i", "320"),  # motorizace se orizne
        ("BMW", "320d", "320"),
        ("BMW", "130i", "130"),
        ("VW", "Golf", "GOLF"),
        ("Škoda", "Octavia", "OCTAVIA"),
        ("Audi", "S3", "S3"),
        ("VW", "e-up!", "EUP"),  # nealfanumericke znaky pryc
    ],
)
def test_model_key_normalisation(make, model, expected):
    assert model_key(make, model) == expected


@pytest.mark.parametrize(
    "make,model,expected",
    [
        ("VW", "Golf", (25200, 14)),
        ("Volkswagen", "Golf", (25200, 14)),
        ("Škoda", "Octavia", (22900, 10)),
        ("BMW", "320i", (3500, 10)),
        ("BMW", "320d", (3500, 10)),  # benzin i diesel sdili model bucket
        ("Ford", "Focus", (9000, 20)),
        ("Ford", "Mustang", None),  # znacku zname, model ne
        ("Tesla", "Model 3", None),  # neznama znacka
        (None, "Golf", None),
        ("VW", None, None),
    ],
)
def test_resolve_ids(make, model, expected):
    assert resolve_ids(make, model, CATALOG) == expected


def test_resolve_ids_tolerates_empty_catalog():
    assert resolve_ids("VW", "Golf", {}) is None


# --- automaticke doplneni pri pridani noveho auta ---


def test_ensure_catalog_skips_network_when_all_known(monkeypatch):
    """Kdyz katalog vsechno zna, nesahne se na sit vubec."""
    from app.config import Watch
    from app import mobilede_catalog as mc

    called = False

    def boom(*a, **kw):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(mc, "load_catalog", lambda: CATALOG)
    monkeypatch.setattr(mc, "resolve_missing_makes", boom)

    watch = Watch(
        model="golf_gti",
        generation="mk7",
        label="VW Golf GTI",
        portal_params={"mobilede": {"make": "VW", "model": "Golf"}},
    )
    assert mc.ensure_catalog_for_watches([watch]) == 0
    assert called is False


def test_ensure_catalog_fetches_unknown_make(monkeypatch):
    from app.config import Watch
    from app import mobilede_catalog as mc

    asked: list[list[str]] = []

    def fake_resolve(catalog, makes, force=False):
        asked.append(makes)
        assert force is True  # znamou znacku je nutne prenacist kvuli novemu modelu
        return 3

    monkeypatch.setattr(mc, "load_catalog", lambda: dict(CATALOG))
    monkeypatch.setattr(mc, "resolve_missing_makes", fake_resolve)
    monkeypatch.setattr(mc, "save_catalog", lambda c: None)

    watch = Watch(
        model="tesla_m3",
        generation="vse",
        label="Tesla Model 3",
        portal_params={"mobilede": {"make": "Tesla", "model": "Model 3"}},
    )
    assert mc.ensure_catalog_for_watches([watch]) == 3
    assert asked == [["Tesla"]]


def test_ensure_catalog_survives_network_failure(monkeypatch):
    """Vypadek site nesmi shodit beh — jen se pouzije slabsi fulltext."""
    from app.config import Watch
    from app import mobilede_catalog as mc

    def boom(*a, **kw):
        raise RuntimeError("Akamai")

    monkeypatch.setattr(mc, "load_catalog", lambda: dict(CATALOG))
    monkeypatch.setattr(mc, "resolve_missing_makes", boom)

    watch = Watch(
        model="tesla_m3",
        generation="vse",
        label="Tesla",
        portal_params={"mobilede": {"make": "Tesla", "model": "Model 3"}},
    )
    assert mc.ensure_catalog_for_watches([watch]) == 0
