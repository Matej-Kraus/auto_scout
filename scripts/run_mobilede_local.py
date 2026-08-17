"""Ruční/diagnostický běh JEN mobile.de (rezidenční IP).

    python -m scripts.run_mobilede_local

Denní automat pro VŠECHNY portály (včetně mobile.de) je
`scripts/run_daily_local.py` (viz deploy/com.carscout.dailylocal.plist) — tenhle
skript použij jen když chceš izolovaně dotáhnout/oladit mobile.de samotné.
Vyžaduje: pip install -e ".[scrapling]" && scrapling install.

Watche bez explicitních portal_params["mobilede"] dostanou parametry odvozené
z kleinanzeigen bloku (text, roky, cena v EUR) — jednou definuješ, všude hledá.
"""

from __future__ import annotations

import logging

from app.alerting import process_alerts
from app.db import init_db, session_scope
from app.pipeline import run_pipeline
from app.run_once import load_all_watches
from app.scrapers.mobilede_local import MobileDeLocalScraper
from app.watch_builder import ensure_mobilede_params

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("mobilede_local")


def main() -> None:
    init_db()
    with session_scope() as session:
        watches = [ensure_mobilede_params(w) for w in load_all_watches(session)]
        active = [w for w in watches if w.portal_params.get("mobilede")]
        logger.info("mobile.de lokalne: %d watchu", len(active))
        diff = run_pipeline(session, active, [MobileDeLocalScraper()])
        sent = process_alerts(session, diff)
    logger.info("Hotovo: %s, alertu %d", diff.summary, sent)


if __name__ == "__main__":
    main()
