"""Testy formatovani Telegram alertu + dry-run send."""

from __future__ import annotations

from app.models import Listing
from app.notify.telegram import format_alert, send_message
from app.scoring.engine import DealScore


def _listing(**kw):
    base = dict(
        source="sauto",
        source_id="1",
        model="audi_s3",
        generation="8p",
        year=2011,
        mileage_km=140_000,
        transmission="manual",
        drivetrain="awd",
        price_czk=215_000,
        price_original=215_000,
        currency="CZK",
        url="https://www.sauto.cz/x/1",
        title="Audi S3 2.0 TFSI quattro",
    )
    base.update(kw)
    return Listing(**base)


def _score(pct=0.18, method="regression", bonuses=None):
    return DealScore(
        value=0.23,
        expected_price=262_000,
        pct_below=pct,
        method=method,
        bonuses=bonuses if bonuses is not None else {"manual": 0.05, "drivetrain": 0.03},
    )


def test_format_new_alert_contents():
    msg = format_alert(_listing(), _score(), "new")
    assert "🔥" in msg
    assert "Audi S3 2.0 TFSI quattro" in msg
    assert "215 000 Kč" in msg  # mezerovany format
    assert "18 % pod predikce" in msg
    assert "manuál" in msg
    assert "AWD" in msg
    assert "https://www.sauto.cz/x/1" in msg.splitlines()[-1]


def test_format_price_drop_shows_old_and_new():
    msg = format_alert(_listing(price_czk=199_000), _score(), "price_drop", old_price=230_000)
    assert "📉" in msg
    assert "230 000 Kč" in msg
    assert "199 000 Kč" in msg


def test_format_median_basis_label():
    msg = format_alert(_listing(), _score(method="median"), "new")
    assert "pod mediánu" in msg


def test_format_no_pct_when_not_below():
    msg = format_alert(_listing(), _score(pct=0.0), "new")
    assert "pod" not in msg  # nezobrazuj nesmyslne "0 % pod"


def test_send_message_dry_run_returns_false():
    # NOTIFY_ENABLED=false ve vychozim configu → jen log, neposila
    assert send_message("test") is False
