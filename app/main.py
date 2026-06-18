"""FastAPI: read API pro dashboard + rucni trigger pipeline.

Lokalne:  uvicorn app.main:app --reload
Na Vercelu se /api/listings nasadi jako serverless funkce (read-only z Neonu).
Connection string jen z env, nikdy do frontendu.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api_schemas import ListingDetailOut, ListingOut, PricePoint
from app.db import SessionLocal, init_db
from app.models import Listing
from app.scoring.engine import score_listing

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Car Deal Hunter", version="0.1.0", lifespan=lifespan)

# Dashboard (Vite dev / Vercel) musi smet cist API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # read-only API, klidne otevrene
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _score_all(listings: list[Listing]) -> dict[int, "object"]:
    """Spocita deal skore pro vsechny listingy (dataset = stejny model+generace)."""
    by_group: dict[tuple[str, str], list[Listing]] = defaultdict(list)
    for lst in listings:
        by_group[(lst.model, lst.generation)].append(lst)

    scores: dict[int, object] = {}
    for group in by_group.values():
        for lst in group:
            scores[lst.id] = score_listing(lst, group)
    return scores


def _to_out(lst: Listing, score) -> ListingOut:
    return ListingOut(
        id=lst.id,
        source=lst.source,
        model=lst.model,
        generation=lst.generation,
        year=lst.year,
        mileage_km=lst.mileage_km,
        transmission=lst.transmission,
        drivetrain=lst.drivetrain,
        price_czk=lst.price_czk,
        currency=lst.currency,
        url=lst.url,
        title=lst.title,
        first_seen=lst.first_seen,
        last_seen=lst.last_seen,
        is_active=lst.is_active,
        deal_score=score.value if score and score.is_alertable else None,
        expected_price=score.expected_price if score else None,
        pct_below=score.pct_below if score else None,
        score_method=score.method if score else None,
    )


@app.get("/api/listings", response_model=list[ListingOut])
def list_listings(active: bool = True, model: str | None = None) -> list[ListingOut]:
    """Inzeraty serazene podle deal skore (nejlepsi dealy nahore)."""
    with SessionLocal() as session:
        stmt = select(Listing)
        if active:
            stmt = stmt.where(Listing.is_active.is_(True))
        if model:
            stmt = stmt.where(Listing.model == model)
        listings = list(session.scalars(stmt).all())

        scores = _score_all(listings)
        out = [_to_out(lst, scores.get(lst.id)) for lst in listings]

    out.sort(key=lambda x: (x.deal_score if x.deal_score is not None else -1e9), reverse=True)
    return out


@app.get("/api/listings/{listing_id}", response_model=ListingDetailOut)
def get_listing(listing_id: int) -> ListingDetailOut:
    """Detail inzeratu vc. historie cen (pro graf)."""
    with SessionLocal() as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            raise HTTPException(status_code=404, detail="Inzerat nenalezen")

        group = list(
            session.scalars(
                select(Listing).where(
                    Listing.model == listing.model,
                    Listing.generation == listing.generation,
                    Listing.is_active.is_(True),
                )
            ).all()
        )
        if listing not in group:
            group.append(listing)
        score = score_listing(listing, group)

        history = sorted(listing.price_history, key=lambda p: p.seen_at)
        base = _to_out(listing, score)
        return ListingDetailOut(
            **base.model_dump(),
            price_history=[PricePoint(price_czk=p.price_czk, seen_at=p.seen_at) for p in history],
        )


@app.get("/api/models", response_model=list[str])
def list_models() -> list[str]:
    with SessionLocal() as session:
        return [m for (m,) in session.execute(select(Listing.model).distinct()).all()]


@app.post("/api/run")
def trigger_run() -> dict:
    """Rucni spusteni pipeline (lokalni vyvoj). Synchronni — chvili to trva."""
    from app.run_once import main as run_main

    run_main()
    return {"status": "ok"}
