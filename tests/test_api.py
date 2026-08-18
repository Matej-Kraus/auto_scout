"""Testy read API (FastAPI) proti sdilene in-memory DB."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_mod
from app.models import Base, Listing, PriceHistory


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(main_mod, "SessionLocal", TestSession)
    monkeypatch.setattr(main_mod, "init_db", lambda: None)

    now = datetime.now(timezone.utc)
    with TestSession() as s:
        for i in range(10):
            s.add(
                Listing(
                    source="sauto",
                    source_id=str(i),
                    model="audi_s3",
                    generation="8p",
                    year=2010,
                    mileage_km=140_000,
                    transmission="manual",
                    drivetrain="awd",
                    price_czk=260_000 - i * 9_000,
                    price_original=260_000,
                    currency="CZK",
                    url=f"https://x/{i}",
                    title=f"Audi S3 #{i}",
                    first_seen=now,
                    last_seen=now,
                    is_active=True,
                )
            )
        s.flush()
        s.add(PriceHistory(listing_id=1, price_czk=260_000, seen_at=now))
        s.commit()

    with TestClient(main_mod.app) as c:
        yield c


def test_listings_sorted_by_score_desc(client):
    data = client.get("/api/listings").json()
    assert len(data) == 10
    scores = [d["deal_score"] for d in data if d["deal_score"] is not None]
    assert scores == sorted(scores, reverse=True)
    # nejlevnejsi (#9) by mel byt nahore a mit nejvyssi pct_below
    assert data[0]["price_czk"] == 260_000 - 9 * 9_000


def test_listing_detail_has_history(client):
    detail = client.get("/api/listings/1").json()
    assert detail["id"] == 1
    assert len(detail["price_history"]) == 1
    assert detail["price_history"][0]["price_czk"] == 260_000


def test_listing_404(client):
    assert client.get("/api/listings/9999").status_code == 404


def test_models_endpoint(client):
    assert client.get("/api/models").json() == ["audi_s3"]


def test_filter_by_model(client):
    data = client.get("/api/listings?model=bmw_130i").json()
    assert data == []


def test_status_endpoint(client):
    st = client.get("/api/status").json()
    assert st["total_listings"] == 10
    assert st["active_listings"] == 10
    assert st["by_model"] == {"audi_s3": 10}
    assert st["last_run"] is not None
    # 10 skoro identickych aut je zamerne PRILIS MALO dat na "hot deal" — scoring
    # pri nizke duvere skore stahuje (viz SCORE_CONFIDENCE_K). Kalibraci tieru
    # testuje tests/test_scoring.py na realistickem vzorku.
    assert st["hot_deals"] == 0


def test_junk_listings_hidden_by_default(client, monkeypatch):
    """Bourana auta a vraky se v seznamu vubec neobjevi."""
    from datetime import datetime, timezone

    from app import main as m

    now = datetime.now(timezone.utc)
    with m.SessionLocal() as s:
        s.add(
            Listing(
                source="kleinanzeigen",
                source_id="wreck",
                model="audi_s3",
                generation="8p",
                year=2010,
                mileage_km=140_000,
                price_czk=60_000,
                price_original=60_000,
                currency="CZK",
                url="https://x/wreck",
                title="Audi S3 Frontschaden",
                first_seen=now,
                last_seen=now,
                is_active=True,
            )
        )
        s.commit()

    urls = [d["url"] for d in client.get("/api/listings").json()]
    assert "https://x/wreck" not in urls

    # pro diagnostiku je porad dosahnutelne
    junk = client.get("/api/listings?include_junk=true").json()
    wreck = next(d for d in junk if d["url"] == "https://x/wreck")
    assert wreck["implausible"] == "damage"
