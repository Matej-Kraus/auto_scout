"""EUR->CZK kurz z CNB, cache na den (soubor + in-memory)."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# CNB denni kurz, textovy format (radky "zeme|mena|mnozstvi|kod|kurz").
CNB_URL = "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt"
_CACHE_FILE = Path(".fx_cache.json")
_FALLBACK_EUR_CZK = 25.0  # posledni zachrana, kdyz neni ani cache

_memory: dict[str, float] = {}


def _read_cache() -> dict | None:
    if not _CACHE_FILE.exists():
        return None
    try:
        return json.loads(_CACHE_FILE.read_text())
    except (json.JSONDecodeError, ValueError, OSError):
        return None


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

    cached = _read_cache()
    if cached and cached.get("date") == today and "rate" in cached:
        _memory.update({"date": today, "rate": float(cached["rate"])})
        return _memory["rate"]

    try:
        resp = httpx.get(CNB_URL, timeout=10.0, verify=settings.ssl_verify)
        resp.raise_for_status()
        rate = _parse_cnb(resp.text)
        _memory.update({"date": today, "rate": rate})
        try:
            _CACHE_FILE.write_text(json.dumps({"date": today, "rate": rate}))
        except OSError:
            pass
        return rate
    except Exception as exc:  # noqa: BLE001 — kurz neni kriticky
        # Radsi posledni znamy (treba i vcerejsi) kurz nez nahodne cislo.
        if cached and "rate" in cached:
            stale = float(cached["rate"])
            logger.warning("CNB nedostupne (%s), pouzivam posledni kurz %.3f", exc, stale)
            return stale
        logger.warning("CNB nedostupne (%s), bez cache → fallback %.2f", exc, _FALLBACK_EUR_CZK)
        return _FALLBACK_EUR_CZK
