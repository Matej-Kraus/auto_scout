"""EUR->CZK kurz z CNB, cache na den (soubor + in-memory)."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# CNB denni kurz, textovy format (radky "zeme|mena|mnozstvi|kod|kurz").
CNB_URL = "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt"
_CACHE_FILE = Path(".fx_cache.json")
_FALLBACK_EUR_CZK = 25.0  # pouzije se kdyz CNB nedostupne

_memory: dict[str, float] = {}


def _parse_cnb(text: str) -> float:
    """Vytahne EUR kurz (za 1 EUR) z CNB textove odpovedi."""
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) == 5 and parts[3] == "EUR":
            amount = int(parts[2])
            rate = float(parts[4].replace(",", "."))
            return rate / amount
    raise ValueError("EUR kurz nenalezen v odpovedi CNB")


def get_eur_czk() -> float:
    """Vrati kolik CZK je 1 EUR. Cache na dnesni datum."""
    today = date.today().isoformat()

    if _memory.get("date") == today and "rate" in _memory:
        return _memory["rate"]

    if _CACHE_FILE.exists():
        try:
            cached = json.loads(_CACHE_FILE.read_text())
            if cached.get("date") == today:
                _memory.update({"date": today, "rate": float(cached["rate"])})
                return _memory["rate"]
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    try:
        resp = httpx.get(CNB_URL, timeout=10.0)
        resp.raise_for_status()
        rate = _parse_cnb(resp.text)
    except Exception as exc:  # noqa: BLE001 — kurz neni kriticky, fallback
        logger.warning("CNB kurz nedostupny (%s), pouzivam fallback %.2f", exc, _FALLBACK_EUR_CZK)
        rate = _FALLBACK_EUR_CZK

    _memory.update({"date": today, "rate": rate})
    try:
        _CACHE_FILE.write_text(json.dumps({"date": today, "rate": rate}))
    except OSError:
        pass
    return rate
