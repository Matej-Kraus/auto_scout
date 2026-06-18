"""Testy zachyceni padu scraperu + health notifikace."""

from __future__ import annotations

from app.alerting import notify_failures
from app.config import Watch
from app.pipeline import DiffResult, run_pipeline
from app.scrapers.base import Scraper, SearchQuery

WATCH = Watch(model="bmw_130i", generation="e87", label="BMW 130i E87")


class BrokenScraper(Scraper):
    name = "sauto"

    def fetch_listings(self, query: SearchQuery):
        raise RuntimeError("struktura se zmenila")


def test_scraper_failure_captured_not_fatal(session):
    diff = run_pipeline(session, [WATCH], [BrokenScraper()])
    assert len(diff.failures) == 1
    scraper, watch, err = diff.failures[0]
    assert scraper == "sauto"
    assert watch == "bmw_130i:e87"
    assert "struktura" in err
    # pipeline nespadla, vraci validni vysledek
    assert diff.new == []


def test_notify_failures_dry_run_no_crash():
    diff = DiffResult(failures=[("sauto", "bmw_130i:e87", "boom")])
    notify_failures(diff)  # NOTIFY_ENABLED=false → jen log, nesmi spadnout


def test_notify_failures_noop_when_empty():
    notify_failures(DiffResult())  # zadne failures → nic
