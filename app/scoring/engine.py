"""Deal scoring: jak moc je inzerat pod ocekavanou cenou + bonusy.

Predikce ceny: linearni regrese cena ~ rok + km (numpy lstsq).
Pri malo datech (< MIN_SAMPLES_FOR_REGRESSION) fallback na median.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from app.config import BUDGET_MAX_CZK, MIN_SAMPLES_FOR_REGRESSION
from app.models import Listing

logger = logging.getLogger(__name__)


@dataclass
class DealScore:
    """Vysledek bodovani jednoho inzeratu."""

    value: float  # vysledne skore (vyssi = lepsi deal); ~ podil pod predikci + bonusy
    expected_price: float | None  # predikovana/median cena trhu
    pct_below: float | None  # kolik % pod ocekavanou cenou (0.22 = 22 % pod)
    method: str  # "regression" | "median" | "insufficient"
    bonuses: dict[str, float]  # rozpad bonusu

    @property
    def is_alertable(self) -> bool:
        return self.method != "insufficient"


def _fit_predict(samples: list[Listing], target: Listing) -> float | None:
    """Linearni regrese cena ~ rok + km na vzorcich; vrati predikci pro target.

    Vyzaduje u target i vzorku znamy rok a km. None kdyz to nejde spocitat.
    """
    rows = [
        (s.year, s.mileage_km, s.price_czk)
        for s in samples
        if s.year is not None and s.mileage_km is not None and s.price_czk
    ]
    if len(rows) < MIN_SAMPLES_FOR_REGRESSION:
        return None
    if target.year is None or target.mileage_km is None:
        return None

    arr = np.array(rows, dtype=float)
    x = np.column_stack([np.ones(len(arr)), arr[:, 0], arr[:, 1]])  # [1, rok, km]
    y = arr[:, 2]
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    pred = coef @ np.array([1.0, target.year, target.mileage_km])
    return float(pred) if pred > 0 else None


def _bonuses(listing: Listing, samples: list[Listing]) -> dict[str, float]:
    """Bonusove body za preference (manual, nizky km, RWD/AWD)."""
    bonuses: dict[str, float] = {}

    if listing.transmission == "manual":
        bonuses["manual"] = 0.05

    if listing.drivetrain in ("rwd", "awd"):
        bonuses["drivetrain"] = 0.03

    # nizky najezd vuci rocniku: porovnej s medianem km u podobne starych vozu
    if listing.mileage_km is not None:
        mileages = [s.mileage_km for s in samples if s.mileage_km is not None]
        if len(mileages) >= MIN_SAMPLES_FOR_REGRESSION:
            median_km = float(np.median(mileages))
            if median_km > 0 and listing.mileage_km < median_km:
                # az +0.05 podle toho jak moc je pod medianem
                ratio = (median_km - listing.mileage_km) / median_km
                bonuses["low_mileage"] = round(min(ratio, 1.0) * 0.05, 4)

    return bonuses


def score_listing(listing: Listing, samples: list[Listing]) -> DealScore:
    """Spocita deal skore inzeratu vuci datasetu `samples` (stejny model+generace).

    `samples` by mely byt aktivni inzeraty stejneho modelu+generace (vc. tohoto).
    """
    usable = [s for s in samples if s.price_czk]
    bonuses = _bonuses(listing, usable)
    bonus_sum = sum(bonuses.values())

    expected = _fit_predict(usable, listing)
    method = "regression"

    if expected is None:
        prices = [s.price_czk for s in usable]
        if len(prices) >= MIN_SAMPLES_FOR_REGRESSION:
            expected = float(np.median(prices))
            method = "median"
        else:
            # Malo dat: nepocitej skore z trhu, jen oznac jako nehodnotitelne.
            # Pipeline muze stejne poslat "novy inzerat v rozpoctu" zvlast.
            return DealScore(
                value=bonus_sum,
                expected_price=None,
                pct_below=None,
                method="insufficient",
                bonuses=bonuses,
            )

    pct_below = (expected - listing.price_czk) / expected
    value = pct_below + bonus_sum
    return DealScore(
        value=round(value, 4),
        expected_price=round(expected, 0),
        pct_below=round(pct_below, 4),
        method=method,
        bonuses=bonuses,
    )


def in_budget(listing: Listing) -> bool:
    """Je inzerat v rozpoctu (horni hranice)? Pro fallback 'novy v rozpoctu'."""
    return bool(listing.price_czk) and listing.price_czk <= BUDGET_MAX_CZK
