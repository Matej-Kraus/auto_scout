"""Konfigurace: env Settings + natvrdo zadane watch listy."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url

logger = logging.getLogger(__name__)

_SQLITE_FALLBACK = "sqlite:///local.db"


def normalize_db_url(v: object) -> str:
    """Zrobustní DATABASE_URL: opraví běžné chyby v Neon stringu a nikdy nespadne.

    Řeší nejčastější pasti (proto padal cron):
    - prázdná / nenastavená hodnota (Actions bez secretu) → SQLite
    - obalující uvozovky   "postgresql://…"  → oříznou
    - prefix z Neon tlačítka  psql 'postgresql://…'  → odstraní
    - schéma postgres:// / postgresql:// → povýší na +psycopg (nainstalovaný driver)
    - cokoli, co pak stejně nejde naparsovat → SQLite fallback (+ hlasitý warning),
      ať pipeline běží a pošle notifikace místo pádu celého workflow.
    """
    if not isinstance(v, str) or not v.strip():
        return _SQLITE_FALLBACK

    s = v.strip()
    if s.lower().startswith("psql "):
        s = s[5:].strip()
    s = s.strip("'").strip('"').strip()

    if s.startswith("postgresql://"):
        s = "postgresql+psycopg://" + s[len("postgresql://"):]
    elif s.startswith("postgres://"):
        s = "postgresql+psycopg://" + s[len("postgres://"):]

    try:
        make_url(s)
    except Exception:  # noqa: BLE001 — radeji SQLite nez shodit cely beh
        logger.error(
            "DATABASE_URL nejde naparsovat (%r…) → docasny fallback na SQLite. "
            "Zkontroluj secret: ma byt 'postgresql+psycopg://user:pass@host/db?sslmode=require', "
            "bez uvozovek a bez 'psql ' na zacatku.",
            s[:25],
        )
        return _SQLITE_FALLBACK
    return s


class Settings(BaseSettings):
    """Hodnoty z .env / prostredi. Zadne secrets v kodu."""

    database_url: str = "sqlite:///local.db"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    deal_threshold: float = 0.10
    notify_enabled: bool = False

    # Email notifikace (SMTP). Zdarma napr. pres Gmail: smtp.gmail.com:587 +
    # "App password" (ucet -> Security -> App passwords). email_to muze byt vic
    # adres oddelenych carkou.
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""  # default = smtp_user
    email_to: str = ""
    # Lokalne za firemni TLS proxy nastav SSL_VERIFY=false (jinak nech true).
    ssl_verify: bool = True
    # Residential proxy pro tvrde chranene portaly (mobile.de = Akamai).
    # Format: http://user:pass@host:port — bez ni se mobile.de preskakuje.
    scraper_proxy_url: str = ""
    # Retence: PriceHistory starsi nez tolik dni se prune (krome posledniho zaznamu).
    retention_days: int = 120

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: object) -> object:
        return normalize_db_url(v)


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
#
# DE portaly (autoscout24, mobilede) jsou ve vychozim stavu vypnute — vyzaduji
# interni ID portalu, ktere je potreba overit z realne site (Cloudflare blokuje
# cloud IP). Zapnes je tak, ze do portal_params doplnis klic "autoscout24"
# resp. "mobilede". Priklad pro Audi S3 (overene AS24 ID make=9, model=15637):
#     "autoscout24": {"make": 9, "model": 15637, "name_includes": ["s3"],
#                      "year_from": 2006, "year_to": 2013},
#     "mobilede": {"make_model": "1900_24", "name_includes": ["s3"],
#                   "year_from": 2006, "year_to": 2013},
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
            },
            "sbazar": {
                "phrase": "bmw 130i",
                "make": "BMW",
                "require_year": True,
                "name_includes": ["130i"],
                "year_from": 2005,
                "year_to": 2013,
                "price_from": 100_000,
                "price_to": 450_000,
            },
            "autoscout24": {
                "make_slug": "bmw",
                "model_slug": "1er",
                "name_includes": ["130i"],
                "year_from": 2005,
                "year_to": 2013,
                "price_to": 18_000,  # EUR
                "power_from_kw": 180,  # 130i ~195 kW; zúží na silné 1er
            },
            "kleinanzeigen": {
                "search_slug": "bmw-130i",
                "name_includes": ["130i"],
                "year_from": 2005,
                "year_to": 2013,
                "price_to": 18_000,  # EUR
            },
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
            },
            "sbazar": {
                "phrase": "audi s3",
                "make": "Audi",
                "require_year": True,
                "name_includes": ["s3"],
                "year_from": 2006,
                "year_to": 2013,
                "price_from": 100_000,
                "price_to": 450_000,
            },
            "autoscout24": {
                "make_slug": "audi",
                "model_slug": "s3",
                "name_includes": ["s3"],
                "year_from": 2006,
                "year_to": 2013,
                "price_to": 18_000,  # EUR
            },
            "kleinanzeigen": {
                "search_slug": "audi-s3",
                "name_includes": ["s3"],
                "year_from": 2006,
                "year_to": 2013,
                "price_to": 18_000,  # EUR
            },
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
            },
            "sbazar": {
                "phrase": "golf gti",
                "make": "Volkswagen",
                "require_year": True,
                "name_includes": ["golf", "gti"],
                "year_from": 2012,
                "year_to": 2020,
                "price_from": 150_000,
                "price_to": 450_000,
            },
            "autoscout24": {
                "make_slug": "volkswagen",
                "model_slug": "golf-gti",  # vlastni slug jen pro GTI varianty
                "name_includes": ["gti"],
                "year_from": 2012,
                "year_to": 2020,
                "price_to": 18_000,  # EUR
            },
            "kleinanzeigen": {
                "search_slug": "volkswagen-golf-gti",
                "name_includes": ["gti"],
                "year_from": 2012,
                "year_to": 2020,
                "price_to": 18_000,  # EUR
            },
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
