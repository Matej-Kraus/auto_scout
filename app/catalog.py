"""Katalog značek a modelů pro výběr ve formuláři „Přidat auto".

Značky: statický snapshot z AS24 taxonomie (`app/data/makes.json`, 290 značek).
Modely: živě z AS24 taxonomy API per značka, cache v paměti na den — modely se
mění zřídka a katalog není kritický (frontend má fallback na ruční zadání).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_MAKES_FILE = Path(__file__).parent / "data" / "makes.json"
_MODELS_URL = "https://www.autoscout24.de/as24-home/api/taxonomy/cars/makes/{make_id}/models"
_CACHE_TTL_S = 24 * 3600

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.autoscout24.de/",
}

_models_cache: dict[int, tuple[float, list[dict]]] = {}


def get_makes() -> dict:
    """{'top_make_ids': [...], 'makes': [{'id', 'name'}, ...]} ze snapshotu."""
    return json.loads(_MAKES_FILE.read_text(encoding="utf-8"))


def get_models(make_id: int) -> list[dict]:
    """Modely značky z AS24 taxonomie: [{'id', 'name'}, ...]. Cache na den."""
    now = time.time()
    cached = _models_cache.get(make_id)
    if cached and now - cached[0] < _CACHE_TTL_S:
        return cached[1]

    resp = httpx.get(
        _MODELS_URL.format(make_id=make_id),
        headers=_HEADERS,
        timeout=15.0,
        verify=settings.ssl_verify,
    )
    resp.raise_for_status()
    values = (((resp.json().get("models") or {}).get("model") or {}).get("values")) or []
    models = [{"id": v["id"], "name": v["name"]} for v in values if v.get("name")]
    models.sort(key=lambda m: str(m["name"]).lower())

    _models_cache[make_id] = (now, models)
    return models
