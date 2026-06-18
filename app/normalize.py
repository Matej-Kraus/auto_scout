"""Normalizace: RawListing -> dict pro Listing. Parsovani textu na enumy/cisla."""

from __future__ import annotations

import re

from app.fx import get_eur_czk
from app.scrapers.base import RawListing

# --- mapovani prevodovky ---
_MANUAL_HINTS = ("manual", "manuál", "manuelni", "schaltgetriebe", "handgeschakeld", "5q", "6q")
_AUTO_HINTS = ("auto", "automat", "dsg", "tronic", "pdk")

# --- mapovani pohonu ---
_AWD_HINTS = ("quattro", "4motion", "4x4", "awd", "allrad", "xdrive", "4wd", "4matic")
_RWD_HINTS = ("rwd", "zadni", "zadní", "hinterrad", "heckantrieb")
_FWD_HINTS = ("fwd", "predni", "přední", "frontantrieb", "vorderrad")

# Pohon podle modelu (kdyz z textu nic): konstrukcni dany.
_MODEL_DEFAULT_DRIVETRAIN = {
    "bmw_130i": "rwd",
    "audi_s3": "awd",
    "golf_gti": "fwd",
}


def parse_transmission(text: str | None) -> str | None:
    if not text:
        return None
    low = text.lower()
    # auto napovedi maji prednost (DSG obsahuje i "auto"-like vzorce)
    if any(h in low for h in _AUTO_HINTS):
        return "auto"
    if any(h in low for h in _MANUAL_HINTS):
        return "manual"
    return None


def parse_drivetrain(text: str | None, model: str | None = None) -> str | None:
    if text:
        low = text.lower()
        if any(h in low for h in _AWD_HINTS):
            return "awd"
        if any(h in low for h in _RWD_HINTS):
            return "rwd"
        if any(h in low for h in _FWD_HINTS):
            return "fwd"
    if model:
        return _MODEL_DEFAULT_DRIVETRAIN.get(model)
    return None


def parse_int(text: str | int | None) -> int | None:
    """Vytahne cele cislo z textu jako '215 000 Kc' nebo '140.000 km'."""
    if text is None:
        return None
    if isinstance(text, int):
        return text
    digits = re.sub(r"[^\d]", "", str(text))
    return int(digits) if digits else None


def parse_year(text: str | int | None) -> int | None:
    if text is None:
        return None
    if isinstance(text, int):
        return text if 1980 <= text <= 2100 else None
    match = re.search(r"(19|20)\d{2}", str(text))
    return int(match.group(0)) if match else None


def to_czk(price: int, currency: str) -> int:
    if currency.upper() == "CZK":
        return price
    if currency.upper() == "EUR":
        return round(price * get_eur_czk())
    raise ValueError(f"Neznama mena: {currency}")


def normalize(raw: RawListing, model: str, generation: str) -> dict:
    """Prevede RawListing na dict atributu pro Listing."""
    price_original = parse_int(raw.price) or 0
    price_czk = to_czk(price_original, raw.currency)

    return {
        "source": raw.source,
        "source_id": str(raw.source_id),
        "model": model,
        "generation": generation,
        "year": parse_year(raw.year),
        "mileage_km": parse_int(raw.mileage_km),
        "transmission": parse_transmission(
            raw.transmission_text or raw.title
        ),
        "drivetrain": parse_drivetrain(raw.drivetrain_text or raw.title, model),
        "price_czk": price_czk,
        "price_original": price_original,
        "currency": raw.currency.upper(),
        "url": raw.url,
        "title": raw.title,
    }
