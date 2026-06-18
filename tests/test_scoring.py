"""Testy scoring enginu — regrese, median fallback, bonusy, malo dat."""

from __future__ import annotations

from app.models import Listing
from app.scoring.engine import score_listing


def _mk(price, year=2011, km=140000, transmission="manual", drivetrain="rwd"):
    return Listing(
        source="sauto",
        source_id=str(price),
        model="bmw_130i",
        generation="e87",
        year=year,
        mileage_km=km,
        transmission=transmission,
        drivetrain=drivetrain,
        price_czk=price,
        price_original=price,
        currency="CZK",
        url="https://x",
        title="BMW 130i",
    )


def test_insufficient_data():
    target = _mk(200000)
    score = score_listing(target, [target, _mk(220000)])
    assert score.method == "insufficient"
    assert not score.is_alertable
    # bonusy se i tak spocitaji (manual + rwd)
    assert score.value > 0


def test_regression_detects_underpriced():
    # 10 vzorku kolem 250k, jeden levny target
    samples = [_mk(250000 + i * 1000, km=140000 + i * 5000) for i in range(10)]
    target = _mk(180000, km=140000)
    samples.append(target)
    score = score_listing(target, samples)
    assert score.method in ("regression", "median")
    assert score.pct_below > 0  # je pod ocekavanou cenou
    assert score.value > score.pct_below or score.bonuses  # bonusy pricteny


def test_median_fallback_when_no_year_km():
    # dost vzorku, ale target nema rok/km → regrese nejde → median
    samples = [_mk(250000 + i * 1000) for i in range(10)]
    target = _mk(150000, year=None, km=None)
    samples.append(target)
    score = score_listing(target, samples)
    assert score.method == "median"
    assert score.expected_price is not None
    assert score.pct_below > 0


def test_manual_and_drivetrain_bonus():
    samples = [_mk(250000 + i * 1000) for i in range(10)]
    target = _mk(250000)
    score = score_listing(target, samples)
    assert "manual" in score.bonuses
    assert "drivetrain" in score.bonuses
