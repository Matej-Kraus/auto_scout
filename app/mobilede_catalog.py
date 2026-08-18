"""Katalog interních ID mobile.de (znacka -> id, model -> id).

Proc to musi byt presne: mobile.de filtruje podle numerickych ID a nerozpoznany
klic TISE IGNORUJE — vrati nesouvisejici auta misto chyby (overeno 8/2026:
dotaz "VW"/"Golf" textove vratil Mercedes GLA, Ford Focus, Citroën C4).
Bez spravneho ID tedy scraper nedostane rozumny vysledek.

Katalog se drzi v JSON souboru vedle kodu a plni se postupne:
  - zaklad je v repu (znacky + modely, ktere uzivatel hlida)
  - dalsi doplni `python -m scripts.mobilede_catalog_sync` (jeden pruchod
    formularem na znacku; vysledek se ulozi natrvalo)

Klice se normalizuji bez diakritiky a velkymi pismeny ("Škoda" -> "SKODA"),
takze na zapisu v configu/DB nezalezi.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).parent / "data" / "mobilede_ids.json"

# Alias pro znacky, ktere lide pisou jinak nez mobile.de.
_MAKE_ALIASES = {
    "VOLKSWAGEN": "VW",
    "MERCEDES": "MERCEDES-BENZ",
}


def norm(text: str) -> str:
    """'Škoda' -> 'SKODA' (bez diakritiky, velka pismena, bez prebytecnych mezer)."""
    stripped = unicodedata.normalize("NFKD", text.strip())
    return "".join(c for c in stripped if not unicodedata.combining(c)).upper()


def make_key(make: str) -> str:
    key = norm(make)
    return _MAKE_ALIASES.get(key, key)


def model_key(make: str, model: str) -> str:
    """Klic modelu. BMW ma modely bez pripony motorizace ('320', ne '320i'/'320d')."""
    key = re.sub(r"[^A-Z0-9]", "", norm(model))
    if make_key(make) == "BMW":
        key = re.sub(r"[A-Z]+$", "", key)  # "320I"/"320D" -> "320"
    return key


def load_catalog() -> dict:
    if not CATALOG_PATH.exists():
        return {"makes": {}, "models": {}}
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("mobilede katalog nejde precist, zacinam prazdny", exc_info=True)
        return {"makes": {}, "models": {}}


def save_catalog(catalog: dict) -> None:
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )


def resolve_ids(make: str | None, model: str | None, catalog: dict | None = None):
    """(makeId, modelId) pro mobile.de, nebo None kdyz je katalog nezna."""
    if not make or not model:
        return None
    cat = catalog if catalog is not None else load_catalog()

    mk = make_key(make)
    make_id = (cat.get("makes") or {}).get(mk)
    if make_id is None:
        return None

    model_id = (cat.get("models") or {}).get(f"{mk}:{model_key(make, model)}")
    return (int(make_id), int(model_id)) if model_id is not None else None


# --- doplneni z webu (jen pri sync, ne za behu scrapovani) ---

_SEARCH_URL = (
    "https://suchen.mobile.de/fahrzeuge/search.html?isSearchRequest=true&scopeId=C&usage=USED"
)


def resolve_missing_makes(catalog: dict, makes: list[str]) -> int:
    """Dotahne z mobile.de znacky/modely, ktere v katalogu chybi. Vraci pocet pridanych.

    Jeden pruchod strankou na davku (vyber znacky ve <select name="mk"> naplni
    <select name="md">). Bezi jen z lokalni rezidencni IP — viz mobilede_local.
    """
    from scrapling.fetchers import StealthyFetcher

    catalog.setdefault("makes", {})
    catalog.setdefault("models", {})

    todo = []
    for raw_make in makes:
        mk = make_key(raw_make)
        # znacku bereme, kdyz nemame jeji id NEBO pro ni nemame zadne modely
        has_models = any(k.startswith(f"{mk}:") for k in catalog["models"])
        if mk not in catalog["makes"] or not has_models:
            if mk not in todo:
                todo.append(mk)

    if not todo:
        return 0

    logger.info("mobilede katalog: dotahuji %s", ", ".join(todo))
    added = 0

    def action(page):
        nonlocal added
        try:
            page.click(".mde-consent-accept-btn", timeout=4000)
            page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001 — modal se nemusi objevit
            pass

        options = page.eval_on_selector_all(
            'select[name="mk"] option',
            "els => els.map(e => [e.value, e.textContent])",
        )
        for value, label in options:
            if value and label:
                catalog["makes"].setdefault(make_key(label), int(value))

        prev_first = None
        for mk in todo:
            make_id = catalog["makes"].get(mk)
            if make_id is None:
                logger.warning("mobilede katalog: znacku %s stranka nezna", mk)
                continue
            page.select_option('select[name="mk"]', value=str(make_id))
            try:
                page.wait_for_function(
                    "prev => {"
                    " const o = document.querySelector('select[name=\"md\"]').options;"
                    " return o.length > 1 && o[1].value !== prev; }",
                    arg=prev_first,
                    timeout=12000,
                )
            except Exception:  # noqa: BLE001 — jedna znacka navic neni kriticka
                logger.warning("mobilede katalog: modely pro %s se nenacetly", mk)
                continue
            models = page.eval_on_selector_all(
                'select[name="md"] option',
                "els => els.map(e => [e.value, e.textContent])",
            )
            for value, label in models:
                if value and label:
                    catalog["models"][f"{mk}:{model_key(mk, label)}"] = int(value)
                    added += 1
            prev_first = models[1][0] if len(models) > 1 else None
        return page

    StealthyFetcher.fetch(
        _SEARCH_URL,
        headless=True,
        humanize=True,
        os_randomize=True,
        block_webrtc=True,
        google_search=False,
        network_idle=True,
        wait=4000,
        timeout=60000,
        page_action=action,
    )
    return added
