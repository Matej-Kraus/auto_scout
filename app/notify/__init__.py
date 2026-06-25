"""Notifikace — jednotný dispatch na zapnuté kanály (Telegram + Email).

Který kanál se použije, řídí env: NOTIFY_ENABLED (Telegram) a EMAIL_ENABLED.
Oba můžou běžet zároveň. Anti-spam (tabulka Alert) řeší pipeline výš.
"""

from __future__ import annotations

from app.models import Listing
from app.notify.email import format_alert_email, send_email
from app.notify.telegram import format_alert, send_message
from app.scoring.engine import DealScore

__all__ = ["format_alert", "send_message", "dispatch_alert", "dispatch_text"]


def dispatch_alert(
    listing: Listing, score: DealScore, kind: str, old_price: int | None = None
) -> None:
    """Rozešle alert o jednom inzerátu na všechny zapnuté kanály."""
    send_message(format_alert(listing, score, kind, old_price))
    subject, html, text = format_alert_email(listing, score, kind, old_price)
    send_email(subject, html, text)


def dispatch_text(text: str, subject: str = "Car Deal Hunter") -> None:
    """Rozešle prostý text (např. upozornění na rozbitý scraper) na všechny kanály."""
    send_message(text)
    html = "<pre style='font-family:system-ui,Arial,sans-serif'>" + _esc(text) + "</pre>"
    send_email(subject, html, text)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
