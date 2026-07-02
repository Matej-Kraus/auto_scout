"""Sestaveni Watch (portal dotazu) z uzivatelskeho vstupu make/model/variant.

Uzivatel zada napr. make="Škoda", model="Octavia", variant="RS" a tady se z toho
automaticky postavi parametry pro vsechny portaly:
  - Sauto:  manufacturer_model_seo "skoda:octavia" + name_includes ["rs"]
  - Sbazar: fulltext phrase "skoda octavia rs"
  - AS24:   /lst/skoda/octavia + name_includes ["rs"]

Specialni pripady (BMW cislene rady na Sauto = "rada-X") resi mapovaci tabulky.
Kdyz portal slug nesedi (vrati 0 vysledku), ostatni portaly jedou dal — watch
nikdy neshodi pipeline.
"""

from __future__ import annotations

import re
import unicodedata

from app.config import Watch
from app.models import WatchRow

# EUR se prepocitava hrube pro server-side price filtr na AS24 (presny prepocet
# dela normalize pres CNB kurz; tady staci strop, at netahame zbytecne draha auta).
_APPROX_CZK_PER_EUR = 24.0


def slugify(text: str) -> str:
    """'Škoda' -> 'skoda', 'Golf GTI' -> 'golf-gti'."""
    norm = unicodedata.normalize("NFKD", text)
    ascii_txt = norm.encode("ascii", "ignore").decode("ascii").lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", ascii_txt).strip("-")


def model_key_for(make: str, model: str, variant: str = "") -> str:
    parts = [slugify(make), slugify(model)]
    if variant.strip():
        parts.append(slugify(variant))
    return "_".join(p.replace("-", "_") for p in parts if p)


def _sauto_model_seo(make: str, model: str) -> str:
    """Sauto pouziva seo tvar 'znacka:model'. BMW cislene rady maji 'rada-X'."""
    make_slug = slugify(make)
    model_slug = slugify(model)
    if make_slug == "bmw":
        m = re.match(r"^(\d)\d{2}", model_slug)  # "130i" -> rada-1, "335d" -> rada-3
        if m:
            return f"bmw:rada-{m.group(1)}"
        m = re.match(r"^rada-?(\d)$", model_slug)
        if m:
            return f"bmw:rada-{m.group(1)}"
    if make_slug in ("mercedes", "mercedes-benz"):
        return f"mercedes-benz:{model_slug}"
    return f"{make_slug}:{model_slug}"


def _as24_slugs(make: str, model: str) -> tuple[str, str]:
    """AS24 cesta /lst/{make}/{model}. BMW cislene modely maji slug '120' apod."""
    make_slug = slugify(make)
    model_slug = slugify(model)
    if make_slug == "bmw":
        m = re.match(r"^(\d)(\d{2})", model_slug)
        if m:
            # AS24 nema slug pro konkretni motorizaci (130i) — pouzij radu (1er)
            # a motorizaci nech na name_includes.
            return "bmw", f"{m.group(1)}er"
    if make_slug in ("mercedes", "mercedes-benz"):
        return "mercedes-benz", model_slug
    if make_slug == "vw":
        return "volkswagen", model_slug
    return make_slug, model_slug


def _name_tokens(model: str, variant: str) -> list[str]:
    """Tokeny, ktere musi byt v nazvu inzeratu (client-side pojistka)."""
    tokens: list[str] = []
    if re.match(r"^\d{3}\w*$", model.strip().lower()):
        tokens.append(model.strip().lower())  # "130i" — motorizace musi byt v nazvu
    for tok in variant.split():
        tokens.append(tok.lower())
    return tokens


def build_watch(row: WatchRow) -> Watch:
    """Postavi Watch s parametry pro vsechny portaly z jednoho DB radku."""
    make, model, variant = row.make.strip(), row.model_name.strip(), (row.variant or "").strip()
    name_tokens = _name_tokens(model, variant)
    generation = f"{row.year_from or ''}-{row.year_to or ''}".strip("-") or "vse"

    sauto: dict = {"model_seo": _sauto_model_seo(make, model)}
    sbazar: dict = {
        "phrase": " ".join(x for x in (make, model, variant) if x),
        "require_year": True,
        "make": make,  # filtr kategorie znacky (jen cela auta, ne dily)
    }
    as24_make, as24_model = _as24_slugs(make, model)
    as24: dict = {"make_slug": as24_make, "model_slug": as24_model}

    for params in (sauto, sbazar):
        if name_tokens:
            params["name_includes"] = name_tokens
        if row.year_from:
            params["year_from"] = row.year_from
        if row.year_to:
            params["year_to"] = row.year_to
        if row.price_from_czk:
            params["price_from"] = row.price_from_czk
        if row.price_to_czk:
            params["price_to"] = row.price_to_czk

    if name_tokens:
        as24["name_includes"] = name_tokens
    if row.year_from:
        as24["year_from"] = row.year_from
    if row.year_to:
        as24["year_to"] = row.year_to
    if row.price_to_czk:
        as24["price_to"] = int(row.price_to_czk / _APPROX_CZK_PER_EUR)

    label = " ".join(x for x in (make, model, variant) if x)
    return Watch(
        model=row.model_key,
        generation=generation,
        label=label,
        portal_params={"sauto": sauto, "sbazar": sbazar, "autoscout24": as24},
    )
