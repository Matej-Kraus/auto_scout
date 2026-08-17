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

# --- portalovo vlastni hodnoceni ceny vuci trhu ---
# mobile.de i AutoScout24 pouzivaji STEJNOU 5stupnovou skalu (overeno 8/2026 z
# definice filtru na AS24: priceEvaluation 1=Sehr guter Preis .. 5=Hoher Preis).
# Normalizujeme na jazykove nezavisle nazvy, at je scoring nezavisly na portalu.
#
# Hodnota je cenna, protoze burzy ji pocitaji z dat, ktera NEMAME (vybava, VIN
# historie, realne prodejni ceny) — je to nezavisly druhy nazor k nasemu modelu.
PRICE_RATING_SCALE = ("great", "good", "fair", "elevated", "high")

# AS24: ciselna hodnota 1-5 primo v JSON (props.pageProps.listings[].price.priceEvaluation)
_AS24_PRICE_EVAL = {1: "great", 2: "good", 3: "fair", 4: "elevated", 5: "high"}

# mobile.de: enum v JSON blobu ("rating":"VERY_GOOD_PRICE") — jazykove nezavisly,
# proto ma prednost pred textovym labelem.
_MOBILEDE_PRICE_ENUM = {
    "VERY_GOOD_PRICE": "great",
    "GOOD_PRICE": "good",
    "REASONABLE_PRICE": "fair",
    "INCREASED_PRICE": "elevated",
    "HIGH_PRICE": "high",
}

# Fallback z textoveho labelu (kdyby portal enum nedodal). Poradi zalezi:
# nejdriv "sehr" varianty, jinak by je chytilo obecne "gut"/"hoch".
_PRICE_RATING_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("great", ("sehr guter preis", "top preis", "great price", "top-preis")),
    ("good", ("guter preis", "good price")),
    ("fair", ("fairer preis", "fair price", "reasonable price")),
    ("elevated", ("erhöhter preis", "erhoehter preis", "increased price")),
    ("high", ("sehr hoher preis", "very high price", "hoher preis", "high price")),
)

# --- mapovani paliva (poradi = priorita; hybrid/elektro pred benzinem) ---
_FUEL_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("electric", ("elektro", "electric", "elektrisch", "ev ")),
    ("hybrid", ("hybrid", "hybridní", "hybridni", "plug-in", "phev")),
    ("diesel", ("nafta", "diesel", "tdi", "cdi", "hdi")),
    ("lpg", ("lpg", "gpl")),
    ("cng", ("cng", "erdgas", "zemní plyn", "zemni plyn")),
    ("petrol", ("benzín", "benzin", "petrol", "gasoline", "tsi", "tfsi", "gti")),
)

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


def parse_fuel(text: str | None) -> str | None:
    if not text:
        return None
    low = text.lower()
    for fuel, hints in _FUEL_HINTS:
        if any(h in low for h in hints):
            return fuel
    return None


def parse_price_rating(value: str | int | None) -> str | None:
    """Portalove hodnoceni ceny -> spolecna skala PRICE_RATING_SCALE.

    Prijima (v poradi spolehlivosti):
      - int 1-5            = AS24 priceEvaluation
      - enum "GOOD_PRICE"  = mobile.de rating
      - text "Guter Preis" = citelny label (fallback, jazykove zavisly)
    """
    if value is None or value == "":
        return None

    if isinstance(value, int):
        return _AS24_PRICE_EVAL.get(value)

    text = str(value).strip()
    if text.isdigit():
        return _AS24_PRICE_EVAL.get(int(text))
    if text.upper() in _MOBILEDE_PRICE_ENUM:
        return _MOBILEDE_PRICE_ENUM[text.upper()]

    low = text.lower()
    for rating, hints in _PRICE_RATING_HINTS:
        if any(h in low for h in hints):
            return rating
    return None


# --- vykon: "180 kW", "110 KW", "180 kW (245 PS)" → 180 ---
_KW_RE = re.compile(r"(\d{2,3})\s*kw\b", re.IGNORECASE)
# fallback z konskych sil: "245 PS"/"245 hp" → kW (×0.7355)
_PS_RE = re.compile(r"(\d{2,3})\s*(?:PS|hp)\b", re.IGNORECASE)


def parse_power_kw(text: str | None) -> int | None:
    if not text:
        return None
    m = _KW_RE.search(text)
    if m:
        kw = int(m.group(1))
        return kw if 30 <= kw <= 700 else None
    m = _PS_RE.search(text)
    if m:
        kw = round(int(m.group(1)) * 0.7355)
        return kw if 30 <= kw <= 700 else None
    return None


# --- karoserie z textu (CZ + DE) ---
# Slova hledame na hranicich (\b), aby "sw"/"van" nematchovaly uvnitr
# "Volkswagen" apod. Poradi = priorita (kombi/suv pred obecnym sedan).
_BODY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kombi", ("kombi", "combi", "variant", "avant", "touring", "estate", "kombík")),
    ("suv", ("suv", "allroad", "crossover")),
    ("cabrio", ("cabrio", "kabrio", "roadster", "convertible", "spider", "spyder")),
    ("coupe", ("coupe", "coupé", "kupé")),
    ("mpv", ("mpv", "minivan", "scenic", "touran", "sharan", "zafira")),
    ("pickup", ("pickup", "pick-up")),
    ("sedan", ("sedan", "limousine", "limuzína", "limuzina", "saloon", "notchback")),
    ("hatchback", ("hatchback", "liftback", "fließheck", "fliessheck")),
)
_BODY_RE = {
    body: re.compile(r"\b(?:" + "|".join(re.escape(h) for h in hints) + r")\b", re.IGNORECASE)
    for body, hints in _BODY_HINTS
}


def parse_body(text: str | None) -> str | None:
    if not text:
        return None
    for body, _hints in _BODY_HINTS:
        if _BODY_RE[body].search(text):
            return body
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
        "transmission": parse_transmission(raw.transmission_text or raw.title),
        "drivetrain": parse_drivetrain(raw.drivetrain_text or raw.title, model),
        "fuel_type": parse_fuel(raw.fuel_text or raw.title),
        "power_kw": parse_power_kw(raw.power_text or raw.title),
        "body_type": parse_body(raw.body_text or raw.title),
        "price_rating": parse_price_rating(raw.price_rating_text),
        "price_czk": price_czk,
        "price_original": price_original,
        "currency": raw.currency.upper(),
        "url": raw.url,
        "title": raw.title,
        "image_url": raw.image_url,
    }
