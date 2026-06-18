"""Rozhodovani o alertech: vezme diff, spocita skore, posle Telegram, zapise Alert."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Listing
from app.notify.telegram import format_alert, send_message
from app.pipeline import DiffResult, already_alerted, record_alert
from app.scoring.engine import DealScore, in_budget, score_listing

logger = logging.getLogger(__name__)


def _samples_for(session: Session, listing: Listing) -> list[Listing]:
    """Aktivni inzeraty stejneho modelu+generace (dataset pro scoring)."""
    return list(
        session.scalars(
            select(Listing).where(
                Listing.model == listing.model,
                Listing.generation == listing.generation,
                Listing.is_active.is_(True),
            )
        ).all()
    )


def _should_alert(score: DealScore, listing: Listing, kind: str) -> bool:
    """Prah pro alert. Pri malo datech fallback: novy inzerat v rozpoctu."""
    if score.is_alertable:
        return score.value >= settings.deal_threshold
    # insufficient data: jen u novych inzeratu v rozpoctu
    return kind == "new" and in_budget(listing)


def process_alerts(session: Session, diff: DiffResult) -> int:
    """Projde novinky a zlevneni, posle alerty. Vraci pocet odeslanych."""
    sent = 0

    candidates: list[tuple[Listing, str, int | None]] = [
        (lst, "new", None) for lst in diff.new
    ] + [(lst, "price_drop", old) for (lst, old) in diff.price_drops]

    for listing, kind, old_price in candidates:
        if already_alerted(session, listing, kind):
            continue

        score = score_listing(listing, _samples_for(session, listing))
        if not _should_alert(score, listing, kind):
            continue

        text = format_alert(listing, score, kind, old_price)
        send_message(text)  # dry-run kdyz NOTIFY_ENABLED=false
        record_alert(session, listing, kind, score.value)
        sent += 1

    session.flush()
    logger.info("alerting: odeslano %d alertu", sent)
    return sent
