"""Spolecne rozhrani vsech scraperu + datove typy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.config import Watch


@dataclass
class SearchQuery:
    """Vstup pro scraper: ktery vuz hledame + portal-specificke parametry."""

    model: str
    generation: str
    params: dict

    @classmethod
    def from_watch(cls, watch: Watch, scraper_name: str) -> "SearchQuery":
        return cls(
            model=watch.model,
            generation=watch.generation,
            params=watch.portal_params.get(scraper_name, {}),
        )


@dataclass
class RawListing:
    """Syrovy inzerat tak, jak ho vrati portal. Cisteni resi normalize.py."""

    source: str
    source_id: str
    title: str
    url: str
    price: int
    currency: str  # CZK | EUR
    year: int | None = None
    mileage_km: int | None = None
    transmission_text: str | None = None  # syrovy text prevodovky
    drivetrain_text: str | None = None  # syrovy text pohonu
    raw: dict = field(default_factory=dict)  # cela odpoved pro pripadny dalsi parsing


class Scraper(ABC):
    """Kazdy portal implementuje tohle. Sync.

    Scraper MUSI padat hlasite pri zmene struktury portalu (raise),
    ne tise vracet prazdny seznam — viz CLAUDE.md §8.
    """

    name: str

    @abstractmethod
    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        """Stahne a vrati syrove inzeraty pro dany dotaz."""
        ...
