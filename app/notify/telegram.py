"""Telegram notifier — pouze send_message + formatovani alertu.

Pouzivame primo Bot API pres httpx (nepotrebujeme cely python-telegram-bot).
Token a chat_id z env. Anti-spam resi tabulka Alert v pipeline.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.models import Listing
from app.scoring.engine import DealScore

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"

_TRANSMISSION_CZ = {"manual": "manuál", "auto": "automat"}
_DRIVETRAIN_CZ = {"rwd": "RWD", "awd": "AWD", "fwd": "FWD"}


def send_message(text: str) -> bool:
    """Posle zpravu na Telegram. Vraci True pri uspechu.

    Kdyz NOTIFY_ENABLED=false nebo chybi token/chat_id, jen zaloguje (dry run).
    """
    if not settings.notify_enabled:
        logger.info("[dry-run telegram]\n%s", text)
        return False
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram token/chat_id chybi — zprava neodeslana")
        return False

    try:
        resp = httpx.post(
            API_URL.format(token=settings.telegram_bot_token),
            json={
                "chat_id": settings.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        return True
    except Exception:  # noqa: BLE001 — notifikace nesmi shodit pipeline
        logger.exception("Telegram send selhal")
        return False


def _fmt_price(czk: int) -> str:
    return f"{czk:,}".replace(",", " ") + " Kč"


def format_alert(listing: Listing, score: DealScore, kind: str, old_price: int | None = None) -> str:
    """Hezka Markdown zprava o dealu / zlevneni."""
    head = "🔥" if kind == "new" else "📉"
    title = listing.title or f"{listing.model} {listing.generation}"

    specs: list[str] = []
    if listing.year:
        specs.append(str(listing.year))
    if listing.mileage_km is not None:
        specs.append(f"{listing.mileage_km:,}".replace(",", " ") + " km")
    if listing.transmission:
        specs.append(_TRANSMISSION_CZ.get(listing.transmission, listing.transmission))
    if listing.drivetrain:
        specs.append(_DRIVETRAIN_CZ.get(listing.drivetrain, listing.drivetrain))
    spec_line = " · ".join(specs)

    lines = [f"{head} *{_md_escape(title)}*"]
    if spec_line:
        lines.append(spec_line)

    if kind == "price_drop" and old_price:
        lines.append(f"💰 {_fmt_price(old_price)} → *{_fmt_price(listing.price_czk)}*")
    else:
        lines.append(f"💰 *{_fmt_price(listing.price_czk)}*")

    if score.pct_below is not None and score.pct_below > 0:
        basis = "mediánu" if score.method == "median" else "predikce"
        lines.append(f"📊 {round(score.pct_below * 100)} % pod {basis}")

    bonus_labels = {
        "manual": "manuál",
        "drivetrain": "RWD/AWD",
        "low_mileage": "nízký nájezd",
    }
    bonuses = [bonus_labels[k] for k in score.bonuses if k in bonus_labels]
    if bonuses:
        lines.append("➕ " + ", ".join(bonuses))

    lines.append(listing.url)
    return "\n".join(lines)


def _md_escape(text: str) -> str:
    # Minimalni escape pro Markdown nadpis (hvezdicky/podtrzitka v nazvu).
    return text.replace("*", "").replace("_", "")
