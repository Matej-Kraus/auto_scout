"""Test Kleinanzeigen scraperu proti syntetickemu HTML (zadna sit)."""

from __future__ import annotations

import httpx
import pytest

from app.config import WATCHES
from app.scrapers.base import SearchQuery
from app.scrapers.kleinanzeigen import KleinanzeigenScraper, parse_listings


def _golf_watch():
    return next(w for w in WATCHES if w.model == "golf_gti")


def _article(adid: str, title: str, price: str, tags: str, href: str | None = None) -> str:
    href = href or f"/s-anzeige/{adid}-216-1"
    tag_html = "".join(f'<span class="simpletag">{t}</span>' for t in tags.split(";") if t)
    return f"""
<article class="aditem" data-adid="{adid}" data-href="{href}">
  <img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/x/{adid}.jpg">
  <a class="ellipsis" href="{href}">{title}</a>
  <p class="aditem-main--middle--price-shipping--price"> {price} € </p>
  <div class="aditem-main--middle--price">{price} €</div>
  {tag_html}
</article>"""


_HTML = "<html><body>" + "".join(
    [
        # sedi: Mk7 GTI s EZ i km
        _article("111", "VW Golf VII GTI Performance", "13.900", "136.000 km;EZ 04/2014"),
        # zahozen: vykupovy inzerat
        _article("222", "Suche VW Golf GTI Motorschaden Ankauf", "3.500", "EZ 01/2015"),
        # zahozen: rok mimo rozsah (2010 < 2012)
        _article("333", "VW Golf VI GTI", "8.000", "180.000 km;EZ 06/2010"),
        # zahozen: bez EZ pri rocnikovem filtru
        _article("444", "VW Golf GTI Teileträger", "5.000", "150.000 km"),
        # zahozen: name_includes (chybi gti)
        _article("555", "VW Golf VII 1.6 TDI", "9.000", "120.000 km;EZ 03/2015"),
    ]
) + "</body></html>"


def test_parses_and_filters():
    query = SearchQuery.from_watch(_golf_watch(), "kleinanzeigen")
    out = parse_listings(_HTML, query)
    assert len(out) == 1
    r = out[0]
    assert r.source == "kleinanzeigen"
    assert r.source_id == "111"
    assert r.price == 13900
    assert r.currency == "EUR"
    assert r.year == 2014
    assert r.mileage_km == 136000
    assert r.image_url and r.image_url.startswith("https://img.kleinanzeigen.de")
    assert r.url.startswith("https://www.kleinanzeigen.de/s-anzeige/")


def test_raises_on_broken_structure():
    query = SearchQuery.from_watch(_golf_watch(), "kleinanzeigen")
    with pytest.raises(RuntimeError, match="aditem"):
        parse_listings("<html><body>neco jineho</body></html>", query)


def test_empty_results_ok():
    query = SearchQuery.from_watch(_golf_watch(), "kleinanzeigen")
    html = "<html><body>Es wurden leider keine Anzeigen gefunden.</body></html>"
    assert parse_listings(html, query) == []


def test_fetch_via_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "s-autos" in str(request.url)
        return httpx.Response(200, text=_HTML)

    scraper = KleinanzeigenScraper(client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = scraper.fetch_listings(SearchQuery.from_watch(_golf_watch(), "kleinanzeigen"))
    assert len(out) == 1
