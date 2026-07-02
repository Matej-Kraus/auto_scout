"""Entrypoint pro jeden beh pipeline. Tohle spousti cron (GitHub Actions).

    python -m app.run_once
"""

from __future__ import annotations

import logging

from app.alerting import notify_failures, process_alerts
from app.config import WATCHES
from app.db import init_db, session_scope
from app.retention import prune_price_history
from app.scrapers.sauto import SautoScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("run_once")


def build_scrapers() -> list:
    """Aktivni scrapery. DE portaly jsou volitelne (sit/Cloudflare/Playwright);
    bez portal_params se uvnitr proste preskoci."""
    scrapers = [SautoScraper()]
    try:
        from app.scrapers.sbazar import SbazarScraper

        scrapers.append(SbazarScraper())
    except Exception:  # noqa: BLE001
        logger.warning("Sbazar scraper se nenacetl, preskakuji", exc_info=True)
    try:
        from app.scrapers.autoscout24 import AutoScout24Scraper

        scrapers.append(AutoScout24Scraper())
    except Exception:  # noqa: BLE001
        logger.warning("AutoScout24 scraper se nenacetl, preskakuji", exc_info=True)
    try:
        from app.scrapers.mobilede import MobileDeScraper

        scrapers.append(MobileDeScraper())
    except Exception:  # noqa: BLE001
        logger.warning("Mobile.de scraper se nenacetl, preskakuji", exc_info=True)
    return scrapers


def load_all_watches(session) -> list:
    """Kuratorske watche z config.py + uzivatelske z DB (tabulka watches)."""
    from sqlalchemy import select

    from app.models import WatchRow
    from app.watch_builder import build_watch

    watches = list(WATCHES)
    known = {w.model for w in watches}
    rows = session.scalars(select(WatchRow).where(WatchRow.enabled.is_(True))).all()
    for row in rows:
        if row.model_key not in known:
            watches.append(build_watch(row))
            known.add(row.model_key)
    return watches


def main() -> None:
    from app.pipeline import run_pipeline

    init_db()
    scrapers = build_scrapers()

    with session_scope() as session:
        watches = load_all_watches(session)
        logger.info("hlidam %d aut: %s", len(watches), ", ".join(w.label for w in watches))
        diff = run_pipeline(session, watches, scrapers)
        sent = process_alerts(session, diff)
        prune_price_history(session)

    notify_failures(diff)
    logger.info("Hotovo: %s, alertu %d", diff.summary, sent)


if __name__ == "__main__":
    main()
