"""Pydantic schemata pro read API (oddeleno od DB modelu)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ListingOut(BaseModel):
    id: int
    source: str
    model: str
    generation: str
    year: int | None
    mileage_km: int | None
    transmission: str | None
    drivetrain: str | None
    price_czk: int
    currency: str
    url: str
    title: str
    first_seen: datetime
    last_seen: datetime
    is_active: bool
    # scoring (dopocitano za behu)
    deal_score: float | None = None
    expected_price: float | None = None
    pct_below: float | None = None
    score_method: str | None = None


class PricePoint(BaseModel):
    price_czk: int
    seen_at: datetime


class ListingDetailOut(ListingOut):
    price_history: list[PricePoint] = []


class StatusOut(BaseModel):
    last_run: datetime | None  # ~ max(last_seen): kdy pipeline naposledy nesto videla
    last_alert: datetime | None
    total_listings: int
    active_listings: int
    hot_deals: int  # aktivni s deal skore >= 0.18
    by_model: dict[str, int]  # pocet aktivnich na model
