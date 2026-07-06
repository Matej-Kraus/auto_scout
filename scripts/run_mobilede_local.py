"""Denní LOKÁLNÍ běh mobile.de (rezidenční IP) → zapisuje do stejné DB jako cron.

    python -m scripts.run_mobilede_local

Spouští launchd 1× denně (viz deploy/com.carscout.mobilede.plist a README).
Vyžaduje: pip install -e ".[playwright]" && python -m playwright install firefox
a DATABASE_URL v .env mířící na stejnou DB jako GitHub Actions (Neon).

Watche bez explicitních portal_params["mobilede"] dostanou parametry odvozené
z kleinanzeigen bloku (text, roky, cena v EUR) — jednou definuješ, všude hledá.
"""

from __future__ import annotations

import logging

from app.alerting import process_alerts
from app.config import Watch
from app.db import init_db, session_scope
from app.pipeline import run_pipeline
from app.run_once import load_all_watches
from app.scrapers.mobilede_local import MobileDeLocalScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("mobilede_local")


def _with_mobilede_params(watch: Watch) -> Watch:
    """Doplni mobilede params z kleinanzeigen bloku, pokud chybi."""
    if watch.portal_params.get("mobilede"):
        return watch
    ka = watch.portal_params.get("kleinanzeigen")
    if not ka:
        return watch
    md: dict = {"text": ka["search_slug"].replace("-", " ")}
    for key in ("name_includes", "year_from", "year_to", "price_to"):
        if key in ka:
            md[key] = ka[key]
    return Watch(
        model=watch.model,
        generation=watch.generation,
        label=watch.label,
        portal_params={**watch.portal_params, "mobilede": md},
    )


def main() -> None:
    init_db()
    with session_scope() as session:
        watches = [_with_mobilede_params(w) for w in load_all_watches(session)]
        active = [w for w in watches if w.portal_params.get("mobilede")]
        logger.info("mobile.de lokalne: %d watchu", len(active))
        diff = run_pipeline(session, active, [MobileDeLocalScraper()])
        sent = process_alerts(session, diff)
    logger.info("Hotovo: %s, alertu %d", diff.summary, sent)


if __name__ == "__main__":
    main()
