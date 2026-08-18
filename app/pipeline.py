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
from app.scrapers.base import RawListing, Scraper, SearchQuery, title_matches

logger = logging.getLogger(__name__)


@dataclass
class DiffResult:
    """Co se v jednom behu zmenilo (pro logy / navazujici alerty)."""

    new: list[Listing] = field(default_factory=list)
    price_drops: list[tuple[Listing, int]] = field(default_factory=list)  # (listing, stara_cena)
    failures: list[tuple[str, str, str]] = field(default_factory=list)  # (scraper, watch, chyba)
    dropped: int = 0  # vyrazeno, protoze uz nesedi na kriteria watche

    @property
    def summary(self) -> str:
        base = f"{len(self.new)} novych, {len(self.price_drops)} zlevneni"
        if self.dropped:
            base += f", {self.dropped} vyrazeno (nesedi na watch)"
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
            except (
                Exception
            ) as exc:  # noqa: BLE001 — jeden zdroj selze, ostatni jedou (CLAUDE.md §8)
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
    diff.dropped = _enforce_watch_criteria(session, watches)
    session.flush()
    logger.info("pipeline diff: %s", diff.summary)
    return diff


def watch_criteria(watch: Watch) -> dict:
    """Sjednoceny pohled na kriteria watche napric portaly (pro zpetnou kontrolu).

    Portal params se lisi (CZK vs EUR, ruzne klice), tady nas zajima jen to, co
    jde overit na ulozenem Listingu: tokeny v nazvu, rozsah roku, strop ceny v CZK.
    """
    sauto = watch.portal_params.get("sauto", {})
    sbazar = watch.portal_params.get("sbazar", {})
    base = sauto or sbazar

    tokens = base.get("name_includes") or []
    # Kdyz nema sauto/sbazar tokeny, zkus DE portaly (uzivatelske watche je maji vsude).
    if not tokens:
        for key in ("autoscout24", "kleinanzeigen", "mobilede"):
            tokens = watch.portal_params.get(key, {}).get("name_includes") or []
            if tokens:
                break

    return {
        "name_includes": tokens,
        "year_from": base.get("year_from"),
        "year_to": base.get("year_to"),
        "price_to": base.get("price_to"),  # CZK (sauto/sbazar jedou v korunach)
    }


def _matches_criteria(lst: Listing, crit: dict) -> bool:
    """Sedi ulozeny inzerat porad na kriteria sveho watche?

    Rok a cena se kontroluji jen kdyz je zname — chybejici udaj neni duvod
    k vyrazeni (nekterym portalum proste chybi).
    """
    if not title_matches(lst.title, crit["name_includes"]):
        return False
    if crit["year_from"] and lst.year is not None and lst.year < crit["year_from"]:
        return False
    if crit["year_to"] and lst.year is not None and lst.year > crit["year_to"]:
        return False
    if crit["price_to"] and lst.price_czk and lst.price_czk > crit["price_to"]:
        return False
    return True


def _enforce_watch_criteria(session: Session, watches: list[Watch]) -> int:
    """Deaktivuje aktivni inzeraty, ktere uz nesedi na kriteria sveho watche.

    Bez tohohle po kazde zmene filtru (nebo opravene chybe v matchovani) zustaval
    stary odpad v DB az do vyprseni staleness — a musel se maza rucne. Ted se
    to srovna samo pri kazdem behu.
    """
    dropped = 0
    for watch in watches:
        crit = watch_criteria(watch)
        if not any(crit.values()):
            continue  # watch bez kriterii — neni co vynucovat

        listings = session.scalars(
            select(Listing).where(Listing.model == watch.model, Listing.is_active.is_(True))
        ).all()

        for lst in listings:
            if not _matches_criteria(lst, crit):
                lst.is_active = False
                dropped += 1

    if dropped:
        logger.info("vyrazeno %d inzeratu nesedicich na kriteria watche", dropped)
    return dropped


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
    for fld in (
        "year",
        "mileage_km",
        "transmission",
        "drivetrain",
        "fuel_type",
        "power_kw",
        "body_type",
        "price_rating",
        "title",
        "url",
        "image_url",
    ):
        setattr(existing, fld, data[fld])

    change = "seen"
    if data["price_czk"] != old_price:
        existing.price_czk = data["price_czk"]
        existing.price_original = data["price_original"]
        session.add(PriceHistory(listing_id=existing.id, price_czk=data["price_czk"], seen_at=now))
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
        session.scalar(select(Alert.id).where(Alert.listing_id == listing.id, Alert.kind == kind))
        is not None
    )
