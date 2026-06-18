"""Testy FX (CNB kurz): parsovani, cache, fallback na posledni znamy kurz."""

from __future__ import annotations

import json
from datetime import date

import pytest

from app import fx

CNB_SAMPLE = """21.06.2026 #118
zeme|mena|mnozstvi|kod|kurz
Dansko|koruna|1|DKK|3,345
EMU|euro|1|EUR|24,910
Japonsko|jen|100|JPY|15,820
"""


def test_parse_cnb_basic():
    assert fx._parse_cnb(CNB_SAMPLE) == pytest.approx(24.910)


def test_parse_cnb_handles_amount():
    text = "x\nzeme|mena|mnozstvi|kod|kurz\nXX|euro|5|EUR|125,0\n"
    assert fx._parse_cnb(text) == pytest.approx(25.0)  # 125 / 5


def test_parse_cnb_raises_when_missing():
    with pytest.raises(ValueError):
        fx._parse_cnb("zeme|mena|mnozstvi|kod|kurz\nUSA|dolar|1|USD|22,0\n")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "_CACHE_FILE", tmp_path / "fx.json")
    monkeypatch.setattr(fx, "_memory", {})
    yield


def _fake_resp(text):
    class R:
        def raise_for_status(self):
            pass

        @property
        def text(self):
            return text

    return R()


def test_fetches_and_caches(monkeypatch):
    monkeypatch.setattr(fx.httpx, "get", lambda *a, **k: _fake_resp(CNB_SAMPLE))
    rate = fx.get_eur_czk()
    assert rate == pytest.approx(24.910)
    cached = json.loads(fx._CACHE_FILE.read_text())
    assert cached["date"] == date.today().isoformat()


def test_uses_stale_cache_when_cnb_down(monkeypatch):
    fx._CACHE_FILE.write_text(json.dumps({"date": "2000-01-01", "rate": 26.5}))

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(fx.httpx, "get", boom)
    assert fx.get_eur_czk() == pytest.approx(26.5)  # vcerejsi kurz, ne hardcoded 25


def test_hardcoded_fallback_only_without_cache(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(fx.httpx, "get", boom)
    assert fx.get_eur_czk() == pytest.approx(fx._FALLBACK_EUR_CZK)
