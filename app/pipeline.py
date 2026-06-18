"""Orchestrace jednoho behu: fetch -> normalize -> upsert -> diff -> (scoring/alert).

Krok 1+2: stahuje, normalizuje, upsertuje a detekuje new / price-drop.
Scoring a Telegram se zapoji v dalsich krocich (jsou volitelne parametry).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import STALE_AFTER_HOURS, Watch
from app.models import Alert, Listing, PriceHistory
from app.normalize import normalize
from app.scrapers.base import RawListing, Scraper, SearchQuery

logger = logging.getLogger(__name__)


@dataclass
class DiffResult:
    """Co se v jednom behu zmenilo (pro logy / navazujici alerty)."""

    new: list[Listing] = field(default_factory=list)
    price_drops: list[tuple[Listing, int]] = field(default_factory=list)  # (listing, stara_cena)
    failures: list[tuple[str, str, str]] = field(default_factory=list)  # (scraper, watch, chyba)

    @property
    def summary(self) -> str:
        base = f"{len(self.new)} novych, {len(self.price_drops)} zlevneni"
        return base + (f", {len(self.failures)} chyb scraperu" if self.failures else "")


def run_pipeline(
    session: Session,
    watches: list[Watch],
    scrapers: list[Scraper],
) -> DiffResult:
    """Projede vsechny watche x scrapery a vrati diff. Jeden scraper smi spadnout."""
    diff = DiffResult()

    for watch in watches:
        for scraper in scrapers:
            query = SearchQuery.from_watch(watch, scraper.name)
            try:
                raws = scraper.fetch_listings(query)
            except Exception as exc:  # noqa: BLE001 — jeden zdroj selze, ostatni jedou (CLAUDE.md §8)
                logger.exception("scraper %s spadl pro watch %s", scraper.name, watch.key)
                diff.failures.append((scraper.name, watch.key, str(exc)[:200]))
                continue

            for raw in raws:
                _listing, change = _upsert(session, raw, watch)
                if change == "new":
                    diff.new.append(_listing)
                elif isinstance(change, tuple) and change[0] == "price_drop":
                    diff.price_drops.append((_listing, change[1]))

    _deactivate_stale(session)
    session.flush()
    logger.info("pipeline diff: %s", diff.summary)
    return diff


def _upsert(session: Session, raw: RawListing, watch: Watch):
    """Vlozi novy nebo aktualizuje existujici Listing. Vraci (listing, change).

    change: "new" | ("price_drop", stara_cena) | "seen" (beze zmeny ceny/nahoru).
    """
    data = normalize(raw, watch.model, watch.generation)
    now = datetime.now(timezone.utc)

    existing = session.scalar(
        select(Listing).where(
            Listing.source == data["source"], Listing.source_id == data["source_id"]
        )
    )

    if existing is None:
        listing = Listing(**data, first_seen=now, last_seen=now, is_active=True)
        session.add(listing)
        session.flush()
        session.add(PriceHistory(listing_id=listing.id, price_czk=listing.price_czk, seen_at=now))
        return listing, "new"

    old_price = existing.price_czk
    existing.last_seen = now
    existing.is_active = True
    # aktualizuj mutovatelne atributy (titulek/km muze portal upravit)
    for fld in ("year", "mileage_km", "transmission", "drivetrain", "title", "url"):
        setattr(existing, fld, data[fld])

    change = "seen"
    if data["price_czk"] != old_price:
        existing.price_czk = data["price_czk"]
        existing.price_original = data["price_original"]
        session.add(
            PriceHistory(listing_id=existing.id, price_czk=data["price_czk"], seen_at=now)
        )
        if data["price_czk"] < old_price:
            change = ("price_drop", old_price)

    return existing, change


def _deactivate_stale(session: Session) -> None:
    """Inzeraty nevidene dele nez STALE_AFTER_HOURS oznac is_active=False.

    Staleness (misto per-run diffu) snese vypadek scraperu i castecne prohledani:
    cokoli, co jsme nedavno videli, zustava aktivni; co dlouho nedoslo, zmizelo z portalu.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS)
    stale = session.scalars(
        select(Listing).where(Listing.is_active.is_(True), Listing.last_seen < cutoff)
    ).all()
    for listing in stale:
        listing.is_active = False
    if stale:
        logger.info("deaktivovano %d zmizelych inzeratu", len(stale))


def record_alert(session: Session, listing: Listing, kind: str, score: float) -> Alert:
    """Zapise odeslany alert (anti-spam) — pouziva krok 3."""
    alert = Alert(listing_id=listing.id, kind=kind, score=score)
    session.add(alert)
    return alert


def already_alerted(session: Session, listing: Listing, kind: str) -> bool:
    """True pokud uz pro tento listing+kind alert odesel (anti-spam)."""
    return (
        session.scalar(
            select(Alert.id).where(Alert.listing_id == listing.id, Alert.kind == kind)
        )
        is not None
    )
