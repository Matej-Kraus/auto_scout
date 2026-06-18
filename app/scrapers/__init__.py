"""Plugin scrapery. Pridani portalu = jeden novy modul implementujici Scraper."""

from app.scrapers.base import RawListing, Scraper, SearchQuery

__all__ = ["RawListing", "Scraper", "SearchQuery"]
