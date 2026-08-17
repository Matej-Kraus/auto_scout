"""Sonda mobile.de — jeden opatrný pokus přes Scrapling StealthyFetcher (Camoufox).

Mobile.de chrání Akamai s reputací IP: opakované požadavky flag zhoršují,
proto tahle sonda udělá JEDINÝ pokus a skončí. Použití:

    python -m scripts.mobilede_probe

- Úspěch  → uloží HTML do scripts/mobilede_snapshot.html a vypíše nalezené
  selektory (parser je v app/scrapers/mobilede_local.py).
- Challenge (Akamai) → vypíše, ať to zkusíš za pár hodin. NEOPAKUJ hned —
  každý pokus flag prodlužuje.

Vyžaduje: pip install -e ".[scrapling]" && scrapling install
(scrapling je zamcen na 0.3.12 — poslední verze s Camoufoxem; Chromium
verze projektu Akamai blokuje uz na TLS urovni, viz CLAUDE.md/mobilede_local.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "mobilede_snapshot.html"
URL = (
    "https://suchen.mobile.de/fahrzeuge/search.html"
    "?isSearchRequest=true&makeModelVariant1.makeId=25200"
    "&makeModelVariant1.modelId=16&minFirstRegistrationDate=2013-01-01"
)


def main() -> int:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        print("Chybi Scrapling: pip install -e '.[scrapling]' && scrapling install")
        return 2

    response = StealthyFetcher.fetch(
        URL,
        headless=True,
        humanize=True,
        os_randomize=True,
        block_webrtc=True,
        google_search=False,
        network_idle=True,
        wait=8000,
        timeout=45000,
    )
    html = response.html_content or ""
    title = (response.css("title::text").get() or "") if html else ""

    if "verweigert" in title.lower() or "denied" in title.lower() or len(html) < 20_000:
        print(f"AKAMAI CHALLENGE (title={title!r}, len={len(html)}).")
        print("IP je flagnuta — zkus znovu za par hodin. Kazdy dalsi pokus flag prodluzuje.")
        SNAPSHOT.write_text(html, encoding="utf-8")
        return 1

    SNAPSHOT.write_text(html, encoding="utf-8")
    print(f"USPECH! title={title!r}, {len(html)} B ulozeno do {SNAPSHOT}")
    print("Ted staci dopsat parser podle snapshotu (selektory nize):")
    for marker in ("details.html", "data-testid=", "listing-title-card-view", "price-label"):
        print(f"  vyskytu {marker!r}: {html.count(marker)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
