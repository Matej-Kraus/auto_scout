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
from sqlalchemy import func, select

from app.api_schemas import (
    ListingDetailOut,
    ListingOut,
    PricePoint,
    StatusOut,
    WatchIn,
    WatchOut,
)
from app.db import SessionLocal, init_db
from app.models import Alert, Listing, WatchRow
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
        fuel_type=lst.fuel_type,
        power_kw=lst.power_kw,
        body_type=lst.body_type,
        price_rating=lst.price_rating,
        price_czk=lst.price_czk,
        currency=lst.currency,
        url=lst.url,
        title=lst.title,
        image_url=lst.image_url,
        first_seen=lst.first_seen,
        last_seen=lst.last_seen,
        is_active=lst.is_active,
        deal_score=score.value if score and score.is_alertable else None,
        expected_price=score.expected_price if score else None,
        pct_below=score.pct_below if score else None,
        score_method=score.method if score else None,
        deal_tier=score.tier if score else "none",
        confidence=score.confidence if score else 0.0,
        portal_agreement=score.portal_agreement if score else None,
        implausible=score.implausible if score else None,
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


@app.get("/api/status", response_model=StatusOut)
def status() -> StatusOut:
    """Zdravi systemu: kdy naposledy bezelo, kolik je aktivnich, kolik hot dealu."""
    with SessionLocal() as session:
        active = list(session.scalars(select(Listing).where(Listing.is_active.is_(True))).all())
        scores = _score_all(active)

        by_model: dict[str, int] = defaultdict(int)
        hot = 0
        for lst in active:
            by_model[lst.model] += 1
            sc = scores.get(lst.id)
            if sc and sc.tier == "hot":
                hot += 1

        last_run = session.scalar(select(func.max(Listing.last_seen)))
        last_alert = session.scalar(select(func.max(Alert.sent_at)))
        total = session.scalar(select(func.count(Listing.id))) or 0

        # Jak rychle dobre kusy mizi: median dnu first_seen->last_seen u zmizelych.
        gone = session.scalars(select(Listing).where(Listing.is_active.is_(False))).all()
        days = sorted(
            max((lst.last_seen - lst.first_seen).total_seconds() / 86400, 0.0) for lst in gone
        )
        median_days = days[len(days) // 2] if days else None

    return StatusOut(
        last_run=last_run,
        last_alert=last_alert,
        total_listings=total,
        active_listings=len(active),
        hot_deals=hot,
        by_model=dict(by_model),
        median_days_to_sell=round(median_days, 1) if median_days is not None else None,
    )


def _count_active(session, model_key: str) -> int:
    return (
        session.scalar(
            select(func.count(Listing.id)).where(
                Listing.model == model_key, Listing.is_active.is_(True)
            )
        )
        or 0
    )


@app.get("/api/catalog/makes")
def catalog_makes() -> dict:
    """Seznam značek pro výběr ve formuláři (statický snapshot)."""
    from app.catalog import get_makes

    return get_makes()


@app.get("/api/catalog/models/{make_id}")
def catalog_models(make_id: int) -> list[dict]:
    """Modely dané značky (živě z AS24 taxonomie, cache na den)."""
    from app.catalog import get_models

    try:
        return get_models(make_id)
    except Exception as exc:  # noqa: BLE001 — katalog neni kriticky
        logger.warning("catalog models %s selhal: %s", make_id, exc)
        raise HTTPException(status_code=502, detail="Katalog modelů je nedostupný") from exc


@app.get("/api/watches", response_model=list[WatchOut])
def list_watches() -> list[WatchOut]:
    """Vsechna hlidana auta: kuratorska z config.py + uzivatelska z DB."""
    from app.config import WATCHES

    out: list[WatchOut] = []
    with SessionLocal() as session:
        for i, w in enumerate(WATCHES):
            out.append(
                WatchOut(
                    id=-(i + 1),  # zaporne id = kuratorske, nejde smazat
                    make=w.label.split()[0],
                    model=" ".join(w.label.split()[1:]) or w.label,
                    model_key=w.model,
                    label=w.label,
                    enabled=True,
                    curated=True,
                    active_listings=_count_active(session, w.model),
                )
            )
        rows = session.scalars(select(WatchRow)).all()
        for r in rows:
            label = " ".join(x for x in (r.make, r.model_name, r.variant) if x)
            out.append(
                WatchOut(
                    id=r.id,
                    make=r.make,
                    model=r.model_name,
                    variant=r.variant or "",
                    year_from=r.year_from,
                    year_to=r.year_to,
                    price_from_czk=r.price_from_czk,
                    price_to_czk=r.price_to_czk,
                    model_key=r.model_key,
                    label=label,
                    enabled=r.enabled,
                    curated=False,
                    active_listings=_count_active(session, r.model_key),
                )
            )
    return out


@app.post("/api/watches", response_model=WatchOut)
def add_watch(data: WatchIn) -> WatchOut:
    """Prida nove hlidane auto. Inzeraty se objevi po pristim behu pipeline."""
    from app.watch_builder import model_key_for

    make, model = data.make.strip(), data.model.strip()
    if not make or not model:
        raise HTTPException(status_code=422, detail="Znacka i model jsou povinne")

    key = model_key_for(make, model, data.variant)
    with SessionLocal() as session:
        existing = session.scalar(select(WatchRow).where(WatchRow.model_key == key))
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Uz hlidam: {key}")
        row = WatchRow(
            make=make,
            model_name=model,
            variant=data.variant.strip(),
            model_key=key,
            year_from=data.year_from,
            year_to=data.year_to,
            price_from_czk=data.price_from_czk,
            price_to_czk=data.price_to_czk,
        )
        session.add(row)
        session.commit()
        label = " ".join(x for x in (make, model, data.variant.strip()) if x)
        return WatchOut(
            **data.model_dump(),
            id=row.id,
            model_key=key,
            label=label,
            enabled=True,
        )


@app.delete("/api/watches/{watch_id}")
def delete_watch(watch_id: int, purge: bool = False) -> dict:
    """Smaze uzivatelsky watch. purge=true smaze i jeho inzeraty."""
    with SessionLocal() as session:
        row = session.get(WatchRow, watch_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Watch nenalezen")
        if purge:
            for lst in session.scalars(select(Listing).where(Listing.model == row.model_key)).all():
                session.delete(lst)
        session.delete(row)
        session.commit()
    return {"status": "deleted"}


@app.post("/api/run")
def trigger_run(
    model_key: str | None = None,
    include_mobilede: bool = False,
    refresh: bool = False,
) -> dict:
    """Rucni spusteni pipeline (bezi lokalne — API je na domaci IP).

    - model_key: prohleda jen jedno auto (po pridani / "Prohledat znovu").
    - include_mobilede: pripoji i mobile.de (Playwright Firefox, jen lokalne).
    - refresh: nejdriv smaze existujici inzeraty toho auta → vysledky jsou cerstve,
      ne "stare X dni" (reset tlacitko u auta).
    """
    from app.alerting import process_alerts
    from app.pipeline import run_pipeline
    from app.run_once import build_scrapers, load_all_watches

    with SessionLocal() as session:
        watches = load_all_watches(session)
        if model_key:
            watches = [w for w in watches if w.model == model_key]
            if not watches:
                raise HTTPException(status_code=404, detail=f"Watch {model_key} nenalezen")

        if refresh and model_key:
            # smaz stara data toho auta → prohledani je od nuly (zadne "duchy")
            for lst in session.scalars(select(Listing).where(Listing.model == model_key)).all():
                session.delete(lst)
            session.flush()

        scrapers = build_scrapers()
        if include_mobilede:
            from app.watch_builder import ensure_mobilede_params

            watches = [ensure_mobilede_params(w) for w in watches]
            try:
                from app.scrapers.mobilede_local import MobileDeLocalScraper

                scrapers.append(MobileDeLocalScraper())
            except Exception:  # noqa: BLE001 — Playwright nemusi byt lokalne
                logger.warning("mobile.de lokalne nedostupne (chybi Playwright?)")

        diff = run_pipeline(session, watches, scrapers)
        sent = process_alerts(session, diff)
        session.commit()
    return {"status": "ok", "summary": diff.summary, "alerts": sent}
