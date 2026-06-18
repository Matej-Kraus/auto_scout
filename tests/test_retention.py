"""Test retence PriceHistory — maze stare, ale necha posledni zaznam/listing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Listing, PriceHistory
from app.retention import prune_price_history


def _listing(session, source_id="1"):
    now = datetime.now(timezone.utc)
    listing = Listing(
        source="sauto",
        source_id=source_id,
        model="audi_s3",
        generation="8p",
        year=2010,
        mileage_km=140_000,
        transmission="manual",
        drivetrain="awd",
        price_czk=250_000,
        price_original=250_000,
        currency="CZK",
        url="https://x",
        title="Audi S3",
        first_seen=now,
        last_seen=now,
        is_active=True,
    )
    session.add(listing)
    session.flush()
    return listing


def test_prunes_old_keeps_latest(session):
    listing = _listing(session)
    now = datetime.now(timezone.utc)
    # 3 stare zaznamy + 1 cerstvy
    for d in (200, 180, 160):
        session.add(
            PriceHistory(
                listing_id=listing.id,
                price_czk=260_000,
                seen_at=now - timedelta(days=d),
            )
        )
    session.add(PriceHistory(listing_id=listing.id, price_czk=250_000, seen_at=now))
    session.flush()

    deleted = prune_price_history(session, keep_days=120)
    assert deleted == 3

    remaining = session.query(PriceHistory).filter_by(listing_id=listing.id).all()
    assert len(remaining) == 1
    assert remaining[0].price_czk == 250_000  # cerstvy zustal


def test_keeps_latest_even_if_old(session):
    """Kdyz ma listing jen stare zaznamy, posledni se NESMI smazat."""
    listing = _listing(session, "2")
    now = datetime.now(timezone.utc)
    for d in (300, 250):
        session.add(
            PriceHistory(listing_id=listing.id, price_czk=260_000, seen_at=now - timedelta(days=d))
        )
    session.flush()

    deleted = prune_price_history(session, keep_days=120)
    assert deleted == 1  # jeden smazan, posledni (i kdyz stary) zustal
    assert session.query(PriceHistory).filter_by(listing_id=listing.id).count() == 1
