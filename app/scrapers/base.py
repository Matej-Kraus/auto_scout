"""Spolecne rozhrani vsech scraperu + datove typy."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache

from app.config import Watch


@lru_cache(maxsize=256)
def _needle_re(needle: str) -> re.Pattern[str]:
    """Vzor pro jeden token z name_includes.

    Hranice slov (\\b), aby "s3" nechytlo "xs3000". Navic zakazany nasledujici
    ".<cislo>", protoze u aut to skoro vzdy znamena objem motoru, ne oznaceni
    modelu: bez toho "s3" matchovalo "Audi a6 s3.0" a pletlo A6 mezi S3
    (overeno na realnych datech 8/2026 - kazilo to i trzni model skupiny).
    """
    return re.compile(rf"\b{re.escape(needle)}\b(?![.,]\d)", re.IGNORECASE)


def title_matches(title: str | None, name_includes: list[str] | tuple[str, ...]) -> bool:
    """Obsahuje titulek VSECHNY pozadovane tokeny (na hranicich slov)?"""
    if not name_includes:
        return True
    if not title:
        return False
    return all(_needle_re(n).search(title) for n in name_includes)


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
    fuel_text: str | None = None  # syrovy text paliva (napr. "Benzín" / "Diesel")
    power_text: str | None = None  # syrovy text s vykonem (napr. "180 kW")
    body_text: str | None = None  # syrovy text karoserie (napr. "Kombi")
    # Portalovo vlastni hodnoceni ceny vuci trhu. Ruzne portaly ruzny tvar:
    # AS24 int 1-5, mobile.de enum "GOOD_PRICE", pripadne citelny label.
    # normalize.parse_price_rating() to sjednoti na spolecnou skalu.
    price_rating_text: str | int | None = None
    image_url: str | None = None  # nahledovy obrazek (prvni foto)
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
