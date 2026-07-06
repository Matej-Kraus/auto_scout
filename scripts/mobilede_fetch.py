"""Stáhne mobile.de pro JEDNO auto a zapíše do DB (odtud to web ukáže).

    python -m scripts.mobilede_fetch golf_gti
    python -m scripts.mobilede_fetch                # vypíše dostupné model_key

On-demand nástroj: mobile.de pustí z domácí IP ~1 požadavek, pak IP na chvíli
flagne. Proto stahuj jedno auto, když ho potřebuješ — ne opakovaně za sebou.
Web dělá totéž přes tlačítko reset ⟳ u auta (API běží na téže IP).
"""

from __future__ import annotations

import logging
import sys

from app.db import init_db, session_scope
from app.models import Listing
from app.pipeline import _upsert
from app.run_once import load_all_watches
from app.scrapers.base import SearchQuery
from app.scrapers.mobilede_local import MobileDeLocalScraper
from app.watch_builder import ensure_mobilede_params

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("mobilede_fetch")


def main() -> int:
    init_db()
    with session_scope() as session:
        watches = {w.model: ensure_mobilede_params(w) for w in load_all_watches(session)}

        if len(sys.argv) < 2:
            print("Pouziti: python -m scripts.mobilede_fetch <model_key>")
            print("Dostupne:", ", ".join(sorted(watches)))
            return 1

        model_key = sys.argv[1]
        watch = watches.get(model_key)
        if watch is None:
            print(f"Neznamy model_key '{model_key}'. Dostupne:", ", ".join(sorted(watches)))
            return 1

        query = SearchQuery.from_watch(watch, "mobilede")
        logger.info("mobile.de dotaz: %r (roky %s-%s)", query.params.get("text"),
                    query.params.get("year_from"), query.params.get("year_to"))

        raws = MobileDeLocalScraper().fetch_listings(query)
        if not raws:
            print("\nmobile.de nic nevratil — IP nejspis potrebuje klid.")
            print("Zkus za ~30 min znovu (nespoustej to opakovane za sebou).")
            return 2

        new = 0
        for raw in raws:
            _listing, change = _upsert(session, raw, watch)
            if change == "new":
                new += 1

        active = session.query(Listing).filter(
            Listing.model == model_key, Listing.source == "mobilede", Listing.is_active.is_(True)
        ).count()
        print(f"\nHotovo: {len(raws)} z mobile.de ({new} novych). "
              f"Celkem {active} mobile.de aut u '{watch.label}'. Uvidis je ve webu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
