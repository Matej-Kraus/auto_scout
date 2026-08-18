"""Doplni katalog interních ID mobile.de (app/data/mobilede_ids.json).

Mobile.de filtruje podle numerickych ID znacky/modelu. Nerozpoznany klic TISE
IGNORUJE a vrati nesouvisejici auta (overeno 8/2026: dotaz "VW/Golf" textove
vratil Mercedes GLA, Ford Focus, Citroën C4). Proto se ID musi znat predem.

    python -m scripts.mobilede_catalog_sync              # doplni chybejici z watchu
    python -m scripts.mobilede_catalog_sync VW Skoda     # jen zadane znacky

Kazda znacka = jedna interakce s formularem (vyber v <select name="mk"> naplni
<select name="md">), takze to stoji jeden pruchod Akamai na davku. Vysledek se
uklada natrvalo — priste uz se nesahne na sit.
"""

from __future__ import annotations

import logging
import sys

from app.mobilede_catalog import load_catalog, resolve_missing_makes, save_catalog
from app.run_once import load_all_watches

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("catalog_sync")


def main() -> int:
    from app.db import init_db, session_scope

    wanted: list[str] = [a for a in sys.argv[1:]]

    if not wanted:
        init_db()
        with session_scope() as session:
            for w in load_all_watches(session):
                md = w.portal_params.get("mobilede") or {}
                if md.get("make"):
                    wanted.append(md["make"])

    catalog = load_catalog()
    added = resolve_missing_makes(catalog, wanted)
    if added:
        save_catalog(catalog)
        print(f"Doplneno {added} znacek/modelu do katalogu.")
    else:
        print("Katalog uz je kompletni, nic se nestahovalo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
