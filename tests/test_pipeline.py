"""Test pipeline: upsert, PriceHistory, detekce new / price-drop, deaktivace."""

from __future__ import annotations

from app.config import Watch
from app.models import Listing, PriceHistory
from app.pipeline import run_pipeline
from app.scrapers.base import RawListing, Scraper, SearchQuery

WATCH = Watch(model="bmw_130i", generation="e87", label="BMW 130i E87")


class FakeScraper(Scraper):
    name = "sauto"

    def __init__(self, batches: list[list[RawListing]]):
        self._batches = batches
        self._i = 0

    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        batch = self._batches[self._i]
        self._i += 1
        return batch


def _raw(source_id="1", price=200000):
    return RawListing(
        source="sauto",
        source_id=source_id,
        title="BMW 130i manuál",
        url="https://x/" + source_id,
        price=price,
        currency="CZK",
        year=2011,
        mileage_km=140000,
        transmission_text="Manuální",
    )


def test_new_listing_detected_and_history_written(session):
    scraper = FakeScraper([[_raw("1", 200000)]])
    diff = run_pipeline(session, [WATCH], [scraper])

    assert len(diff.new) == 1
    listings = session.query(Listing).all()
    assert len(listings) == 1
    assert session.query(PriceHistory).count() == 1


def test_price_drop_detected(session):
    scraper = FakeScraper([[_raw("1", 200000)], [_raw("1", 180000)]])

    diff1 = run_pipeline(session, [WATCH], [scraper])
    assert len(diff1.new) == 1

    diff2 = run_pipeline(session, [WATCH], [scraper])
    assert len(diff2.new) == 0
    assert len(diff2.price_drops) == 1
    listing, old = diff2.price_drops[0]
    assert old == 200000
    assert listing.price_czk == 180000
    # dva zaznamy v historii (vlozeni + zlevneni)
    assert session.query(PriceHistory).count() == 2


def test_price_increase_no_drop_but_history(session):
    scraper = FakeScraper([[_raw("1", 200000)], [_raw("1", 210000)]])
    run_pipeline(session, [WATCH], [scraper])
    diff2 = run_pipeline(session, [WATCH], [scraper])
    assert len(diff2.price_drops) == 0
    assert session.query(PriceHistory).count() == 2  # zmena ceny → novy zaznam


def test_stale_listing_deactivated(session):
    from datetime import datetime, timedelta, timezone

    scraper = FakeScraper([[_raw("1"), _raw("2")], [_raw("1")]])
    run_pipeline(session, [WATCH], [scraper])

    # Listing "2" zestarne (simulace: nevideny dlouho), "1" se znovu vidi v dalsim behu.
    l2 = session.query(Listing).filter_by(source_id="2").one()
    l2.last_seen = datetime.now(timezone.utc) - timedelta(hours=72)
    session.flush()

    run_pipeline(session, [WATCH], [scraper])

    l1 = session.query(Listing).filter_by(source_id="1").one()
    l2 = session.query(Listing).filter_by(source_id="2").one()
    assert l1.is_active is True
    assert l2.is_active is False


# --- zpetne vynucovani kriterii watche ---
# Bez tohohle po zmene filtru (nebo opravene chybe v matchovani) zustaval v DB
# stary odpad az do vyprseni staleness a musel se mazat rucne.

STRICT_WATCH = Watch(
    model="bmw_130i",
    generation="e87",
    label="BMW 130i E87",
    portal_params={
        "sauto": {
            "name_includes": ["130i"],
            "year_from": 2005,
            "year_to": 2013,
            "price_to": 450_000,
        }
    },
)


def _seed(session, **kw):
    """Ulozi aktivni inzerat s vychozimi hodnotami, ktere kriteriim vyhovuji."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    defaults = dict(
        source="sauto",
        source_id="seed",
        model="bmw_130i",
        generation="e87",
        year=2011,
        mileage_km=140_000,
        price_czk=300_000,
        price_original=300_000,
        currency="CZK",
        url="https://x/seed",
        title="BMW 130i manuál",
        first_seen=now,
        last_seen=now,
        is_active=True,
    )
    lst = Listing(**{**defaults, **kw})
    session.add(lst)
    session.flush()
    return lst


def test_listing_with_wrong_name_is_dropped(session):
    bad = _seed(session, source_id="bad", title="BMW 120d")
    good = _seed(session, source_id="good", title="BMW 130i")

    diff = run_pipeline(session, [STRICT_WATCH], [FakeScraper([[]])])

    assert diff.dropped == 1
    assert bad.is_active is False
    assert good.is_active is True


def test_listing_over_price_cap_is_dropped(session):
    pricey = _seed(session, source_id="pricey", price_czk=600_000)
    run_pipeline(session, [STRICT_WATCH], [FakeScraper([[]])])
    assert pricey.is_active is False


def test_listing_outside_year_range_is_dropped(session):
    old = _seed(session, source_id="old", year=2002)
    new = _seed(session, source_id="new", year=2020)
    run_pipeline(session, [STRICT_WATCH], [FakeScraper([[]])])
    assert old.is_active is False
    assert new.is_active is False


def test_missing_year_is_not_dropped(session):
    """Chybejici udaj neni duvod k vyrazeni — nekterym portalum proste chybi."""
    unknown = _seed(session, source_id="unknown", year=None)
    run_pipeline(session, [STRICT_WATCH], [FakeScraper([[]])])
    assert unknown.is_active is True


def test_watch_without_criteria_drops_nothing(session):
    anything = _seed(session, source_id="any", title="uplne jine auto", year=1990)
    diff = run_pipeline(session, [WATCH], [FakeScraper([[]])])  # WATCH nema portal_params
    assert diff.dropped == 0
    assert anything.is_active is True
