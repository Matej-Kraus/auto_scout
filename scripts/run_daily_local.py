"""Jeden denní lokální běh VŠECH portálů (Sauto/Sbazar/AutoScout24/Kleinanzeigen
+ Mobile.de) do jedné lokální DB, kterou čte dashboard (`uvicorn app.main:app`).

    python -m scripts.run_daily_local

Spouští launchd 1× denně (viz deploy/com.carscout.dailylocal.plist) — cíl je
prostě jednou za den otevřít localhost a vidět aktuální stav ze všech bazarů
na jednom místě, bez ručního spouštění jednotlivých scriptů a bez Telegramu
(NOTIFY_ENABLED zůstává false — alerty se jen zapíšou do DB, dashboard je
hlavní rozhraní).

Mobile.de v tomhle běhu dělá max jeden pokus na watch (Akamai) — viz
app/scrapers/mobilede_local.py; pri challenge se ten portál pro zbytek běhu
měkce přeskočí, ostatní portály běží dál beze změny.
"""

from __future__ import annotations

import logging

from app.alerting import process_alerts
from app.db import init_db, session_scope
from app.pipeline import run_pipeline
from app.retention import prune_price_history
from app.run_once import build_scrapers, load_all_watches
from app.scrapers.mobilede_local import MobileDeLocalScraper
from app.watch_builder import ensure_mobilede_params

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("run_daily_local")


def main() -> None:
    init_db()
    scrapers = build_scrapers() + [MobileDeLocalScraper()]

    with session_scope() as session:
        watches = [ensure_mobilede_params(w) for w in load_all_watches(session)]
        logger.info("hlidam %d aut: %s", len(watches), ", ".join(w.label for w in watches))
        diff = run_pipeline(session, watches, scrapers)
        sent = process_alerts(session, diff)
        prune_price_history(session)
    logger.info("Hotovo: %s, alertu %d", diff.summary, sent)


if __name__ == "__main__":
    main()
