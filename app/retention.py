"""Retence: maze stare zaznamy PriceHistory, aby se free DB (0.5 GB) nezaplnila.

Necha vzdy aspon posledni zaznam pro kazdy listing (at zustane aktualni cena
a graf neni prazdny), maze jen stare body historie.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PriceHistory

logger = logging.getLogger(__name__)


def prune_price_history(session: Session, keep_days: int | None = None) -> int:
    """Smaze PriceHistory starsi nez keep_days, krome posledniho zaznamu/listing.

    Vraci pocet smazanych zaznamu.
    """
    days = keep_days if keep_days is not None else settings.retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # ID posledniho (nejnovejsiho) zaznamu pro kazdy listing — ty nechame.
    latest_ids = select(func.max(PriceHistory.id)).group_by(PriceHistory.listing_id)

    result = session.execute(
        delete(PriceHistory).where(
            PriceHistory.seen_at < cutoff,
            PriceHistory.id.not_in(latest_ids),
        )
    )
    deleted = result.rowcount or 0
    if deleted:
        logger.info("retence: smazano %d starych zaznamu PriceHistory", deleted)
    return deleted
