"""Konfigurace: env Settings + natvrdo zadane watch listy."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Hodnoty z .env / prostredi. Zadne secrets v kodu."""

    database_url: str = "sqlite:///local.db"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    deal_threshold: float = 0.10
    notify_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


@dataclass(frozen=True)
class Watch:
    """Jeden hlidany vuz (model + generace) a parametry hledani pro portaly.

    `portal_params` mapuje nazev scraperu na portal-specificke parametry
    (napr. id znacky/modelu na Sauto). Scraper si vytahne ten svuj klic.
    """

    model: str
    generation: str
    label: str
    portal_params: dict[str, dict] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.model}:{self.generation}"


# Vychozi watche dle CLAUDE.md §2. Uzivatel si je tu muze upravit.
#
# portal_params["sauto"] (viz scrapers/sauto.py):
#   model_seo      — "znacka:model" do parametru manufacturer_model_seo (server-side filtr)
#   name_includes  — vsechny tyto substringy musi byt v nazvu (client-side, kvuli generaci/motoru)
#   year_from/to   — rocnikovy filtr (client-side)
#   price_from/to  — server-side cenovy filtr (zuzi objem stahovani)
WATCHES: list[Watch] = [
    Watch(
        model="bmw_130i",
        generation="e87",
        label="BMW 130i E87",
        portal_params={
            "sauto": {
                "model_seo": "bmw:rada-1",
                "name_includes": ["130i"],
                "year_from": 2005,
                "year_to": 2013,
                "price_from": 100_000,
                "price_to": 450_000,
            }
        },
    ),
    Watch(
        model="audi_s3",
        generation="8p",
        label="Audi S3 8P",
        portal_params={
            "sauto": {
                "model_seo": "audi:s3",
                "name_includes": ["s3"],
                "year_from": 2006,
                "year_to": 2013,
                "price_from": 100_000,
                "price_to": 450_000,
            }
        },
    ),
    Watch(
        model="golf_gti",
        generation="mk7",
        label="VW Golf GTI Mk7",
        portal_params={
            "sauto": {
                "model_seo": "volkswagen:golf",
                "name_includes": ["gti"],
                "year_from": 2012,
                "year_to": 2020,
                "price_from": 150_000,
                "price_to": 450_000,
            }
        },
    ),
]


# Cenovy rozpocet (CZK) — vstup do scoringu, viz CLAUDE.md §2.
BUDGET_MIN_CZK = 200_000
BUDGET_MAX_CZK = 300_000

# Min. pocet vzorku pro regresni scoring; pod tim fallback na median.
MIN_SAMPLES_FOR_REGRESSION = 8

# Po kolika hodinach bez videni se inzerat povazuje za zmizely (is_active=False).
# Vychazi z toho, ze cron bezi casto; staleness je robustnejsi nez per-run diff
# (snese vypadek scraperu i castecne prohledani).
STALE_AFTER_HOURS = 48
