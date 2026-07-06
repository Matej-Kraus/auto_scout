"""Email notifier — SMTP přes stdlib (žádná extra závislost).

Zdarma napr. přes Gmail: smtp.gmail.com:587 + "App password"
(Google účet → Security → 2FA → App passwords). Konfigurace v env (viz config.py).
Anti-spam řeší tabulka Alert v pipeline (stejně jako u Telegramu).
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings
from app.models import Listing
from app.scoring.engine import DealScore

logger = logging.getLogger(__name__)

_TRANSMISSION_CZ = {"manual": "manuál", "auto": "automat"}
_DRIVETRAIN_CZ = {"rwd": "RWD", "awd": "AWD", "fwd": "FWD"}
_BONUS_CZ = {
    "manual": "manuál",
    "drivetrain": "RWD/AWD",
    "low_mileage": "nízký nájezd",
    "equipment": "výbava",
}


def _recipients() -> list[str]:
    return [a.strip() for a in settings.email_to.split(",") if a.strip()]


def send_email(subject: str, html_body: str, text_body: str) -> bool:
    """Pošle jeden email. Vrací True při úspěchu.

    Když email_enabled=false nebo chybí SMTP/příjemce → jen zaloguje (dry run).
    Selhání odeslání nesmí shodit pipeline — chytneme a vrátíme False.
    """
    recipients = _recipients()
    if not settings.email_enabled:
        logger.info("[dry-run email] %s", subject)
        return False
    if not settings.smtp_host or not settings.smtp_user or not recipients:
        logger.warning("Email: chybi smtp_host/smtp_user/email_to — neodeslano")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from or settings.smtp_user
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 — notifikace nesmí shodit pipeline
        logger.exception("Email send selhal")
        return False


def _fmt_price(czk: int) -> str:
    return f"{czk:,}".replace(",", " ") + " Kč"


def _specs(listing: Listing) -> str:
    parts: list[str] = []
    if listing.year:
        parts.append(str(listing.year))
    if listing.mileage_km is not None:
        parts.append(f"{listing.mileage_km:,}".replace(",", " ") + " km")
    if listing.transmission:
        parts.append(_TRANSMISSION_CZ.get(listing.transmission, listing.transmission))
    if listing.drivetrain:
        parts.append(_DRIVETRAIN_CZ.get(listing.drivetrain, listing.drivetrain))
    parts.append(listing.source)
    return " · ".join(parts)


def format_alert_email(
    listing: Listing, score: DealScore, kind: str, old_price: int | None = None
) -> tuple[str, str, str]:
    """Vrátí (subject, html_body, text_body) pro jeden inzerát."""
    head = "🔥" if kind == "new" else "📉"
    title = listing.title or f"{listing.model} {listing.generation}"
    subject = f"{head} {title} — {_fmt_price(listing.price_czk)}"

    if kind == "price_drop" and old_price:
        price_html = f'<s style="color:#888">{_fmt_price(old_price)}</s> → <b>{_fmt_price(listing.price_czk)}</b>'
        price_txt = f"{_fmt_price(old_price)} → {_fmt_price(listing.price_czk)}"
    else:
        price_html = f"<b>{_fmt_price(listing.price_czk)}</b>"
        price_txt = _fmt_price(listing.price_czk)

    deal_line_html = deal_line_txt = ""
    if score.pct_below is not None and score.pct_below > 0:
        basis = "mediánu" if score.method == "median" else "predikce"
        deal_line_txt = f"📊 {round(score.pct_below * 100)} % pod {basis}"
        deal_line_html = f'<div style="color:#0a7d2c">📊 {round(score.pct_below * 100)} % pod {basis}</div>'

    bonuses = [_BONUS_CZ[k] for k in score.bonuses if k in _BONUS_CZ]
    bonus_txt = ("➕ " + ", ".join(bonuses)) if bonuses else ""
    bonus_html = f'<div style="color:#555">➕ {", ".join(bonuses)}</div>' if bonuses else ""

    img_html = (
        f'<img src="{listing.image_url}" alt="" '
        f'style="max-width:480px;width:100%;border-radius:8px;display:block;margin:8px 0">'
        if listing.image_url
        else ""
    )

    html = f"""\
<div style="font-family:system-ui,Arial,sans-serif;max-width:520px">
  <h2 style="margin:0 0 4px">{head} {_html_escape(title)}</h2>
  <div style="color:#444">{_html_escape(_specs(listing))}</div>
  {img_html}
  <div style="font-size:18px;margin:6px 0">{price_html}</div>
  {deal_line_html}
  {bonus_html}
  <p><a href="{listing.url}"
        style="display:inline-block;margin-top:8px;padding:10px 16px;background:#111;
               color:#fff;text-decoration:none;border-radius:6px">Otevřít inzerát →</a></p>
</div>"""

    text = "\n".join(
        x for x in [f"{head} {title}", _specs(listing), price_txt, deal_line_txt, bonus_txt, listing.url] if x
    )
    return subject, html, text


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
