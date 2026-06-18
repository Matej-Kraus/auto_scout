"""Testy cross-portal deduplikace + potlaceni dvojitych alertu."""

from __future__ import annotations

from datetime import datetime, timezone

from app.alerting import process_alerts
from app.dedup import find_db_duplicate, same_car
from app.models import Alert, Listing
from app.pipeline import DiffResult


def _mk(session, source, source_id, year=2011, km=140_000, price=215_000, add=True):
    now = datetime.now(timezone.utc)
    listing = Listing(
        source=source,
        source_id=source_id,
        model="audi_s3",
        generation="8p",
        year=year,
        mileage_km=km,
        transmission="manual",
        drivetrain="awd",
        price_czk=price,
        price_original=price,
        currency="CZK",
        url=f"https://{source}/{source_id}",
        title="Audi S3",
        first_seen=now,
        last_seen=now,
        is_active=True,
    )
    if add:
        session.add(listing)
        session.flush()
    return listing


def test_same_car_false_without_year_or_km(session):
    a = _mk(session, "sauto", "1", year=None, add=False)
    b = _mk(session, "autoscout24", "2", add=False)
    assert same_car(a, b) is False


def test_finds_cross_source_duplicate(session):
    _mk(session, "sauto", "1", km=140_500, price=215_000)
    as24 = _mk(session, "autoscout24", "2", km=139_800, price=220_000)  # ~stejny vuz
    dup = find_db_duplicate(session, as24)
    assert dup is not None
    assert dup.source == "sauto"


def test_not_duplicate_when_price_far(session):
    _mk(session, "sauto", "1", price=215_000)
    other = _mk(session, "autoscout24", "2", price=300_000)  # +40 % → jine auto
    assert find_db_duplicate(session, other) is None


def test_not_duplicate_same_source(session):
    _mk(session, "sauto", "1")
    same = _mk(session, "sauto", "2")  # stejny zdroj se neresi jako dup
    assert find_db_duplicate(session, same) is None


def test_process_alerts_suppresses_second_portal(session):
    sauto = _mk(session, "sauto", "1", km=140_000, price=215_000)
    as24 = _mk(session, "autoscout24", "2", km=140_300, price=216_000)

    # 1. behu: alertuje se Sauto (dost levne → v rozpoctu, malo dat → fallback)
    process_alerts(session, DiffResult(new=[sauto]))
    assert session.query(Alert).count() == 1

    # 2. behu: dorazi to same auto z AS24 → NEMA poslat druhy alert
    process_alerts(session, DiffResult(new=[as24]))
    assert session.query(Alert).count() == 1


def test_process_alerts_suppresses_within_single_run(session):
    sauto = _mk(session, "sauto", "1", km=140_000, price=215_000)
    as24 = _mk(session, "autoscout24", "2", km=140_300, price=216_000)
    process_alerts(session, DiffResult(new=[sauto, as24]))
    assert session.query(Alert).count() == 1
