"""Sonda mobile.de — jeden opatrný pokus přes Playwright Firefox.

Mobile.de chrání Akamai s reputací IP: opakované požadavky flag zhoršují,
proto tahle sonda udělá JEDINÝ pokus a skončí. Použití:

    python -m scripts.mobilede_probe

- Úspěch  → uloží HTML do scripts/mobilede_snapshot.html (z něj se dopíše
  parser pro lokální mobile.de runner) a vypíše nalezené selektory.
- Challenge (Akamai) → vypíše, ať to zkusíš za pár hodin. NEOPAKUJ hned —
  každý pokus flag prodlužuje.

Vyžaduje: pip install -e ".[playwright]" && python -m playwright install firefox
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
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Chybi Playwright: pip install -e '.[playwright]' && python -m playwright install firefox")
        return 2

    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=True)
        ctx = browser.new_context(locale="de-DE", viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(8000)
            title = page.title()
            html = page.content()
        finally:
            browser.close()

    if "verweigert" in title.lower() or "denied" in title.lower() or len(html) < 20_000:
        print(f"AKAMAI CHALLENGE (title={title!r}, len={len(html)}).")
        print("IP je flagnuta — zkus znovu za par hodin. Kazdy dalsi pokus flag prodluzuje.")
        return 1

    SNAPSHOT.write_text(html, encoding="utf-8")
    print(f"USPECH! title={title!r}, {len(html)} B ulozeno do {SNAPSHOT}")
    print("Ted staci dopsat parser podle snapshotu (selektory nize):")
    for marker in ("details.html", "data-testid=", "<article", "priceLabel", "application/ld+json"):
        print(f"  vyskytu {marker!r}: {html.count(marker)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
