"""Entrypoint pro jeden beh pipeline. Tohle spousti cron (GitHub Actions).

    python -m app.run_once
"""

from __future__ import annotations

import logging

from app.alerting import process_alerts
from app.config import WATCHES
from app.db import init_db, session_scope
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


def main() -> None:
    from app.pipeline import run_pipeline

    init_db()
    scrapers = build_scrapers()

    with session_scope() as session:
        diff = run_pipeline(session, WATCHES, scrapers)
        sent = process_alerts(session, diff)

    logger.info("Hotovo: %s, alertu %d", diff.summary, sent)


if __name__ == "__main__":
    main()
