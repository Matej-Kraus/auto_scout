"""Testy normalizeru — parsovani textu na cisla a enumy."""

from __future__ import annotations

from app import normalize as n
from app.scrapers.base import RawListing


def test_parse_int_from_messy_text():
    assert n.parse_int("215 000 Kč") == 215000
    assert n.parse_int("140.000 km") == 140000
    assert n.parse_int(134841) == 134841
    assert n.parse_int(None) is None
    assert n.parse_int("cena dohodou") is None


def test_parse_year():
    assert n.parse_year("2011-03-01") == 2011
    assert n.parse_year(2011) == 2011
    assert n.parse_year("Rok 2008") == 2008
    assert n.parse_year(1850) is None
    assert n.parse_year(None) is None


def test_parse_transmission():
    assert n.parse_transmission("Manuální") == "manual"
    assert n.parse_transmission("Automatická DSG") == "auto"
    assert n.parse_transmission("S tronic 7°") == "auto"
    assert n.parse_transmission("VW Golf GTI") is None


def test_parse_drivetrain_from_text_and_model():
    assert n.parse_drivetrain("Audi S3 quattro") == "awd"
    assert n.parse_drivetrain("BMW xDrive") == "awd"
    assert n.parse_drivetrain("nic", model="bmw_130i") == "rwd"
    assert n.parse_drivetrain("nic", model="golf_gti") == "fwd"
    assert n.parse_drivetrain(None, model="audi_s3") == "awd"


def test_normalize_czk():
    raw = RawListing(
        source="sauto",
        source_id="123",
        title="BMW 130i E87 manuál",
        url="https://x",
        price=215000,
        currency="CZK",
        year="2011-03-01",
        mileage_km=140000,
        transmission_text="Manuální",
    )
    data = n.normalize(raw, "bmw_130i", "e87")
    assert data["price_czk"] == 215000
    assert data["price_original"] == 215000
    assert data["year"] == 2011
    assert data["transmission"] == "manual"
    assert data["drivetrain"] == "rwd"  # z modelu


def test_normalize_eur_converts(monkeypatch):
    monkeypatch.setattr(n, "get_eur_czk", lambda: 25.0)
    raw = RawListing(
        source="autoscout24",
        source_id="9",
        title="Audi S3 8P quattro",
        url="https://x",
        price=10000,
        currency="EUR",
        year=2010,
        mileage_km=120000,
    )
    data = n.normalize(raw, "audi_s3", "8p")
    assert data["price_original"] == 10000
    assert data["price_czk"] == 250000
    assert data["currency"] == "EUR"
    assert data["drivetrain"] == "awd"  # quattro
