"""Detekce stejneho auta na vic portalech (anti-spam pres zdroje).

Bez VINu (portaly ho nedavaji) jde o heuristiku: stejny model+generace,
shodny rocnik, podobny najezd a cena → nejspis jeden vuz inzerovany na vic mistech.
Pouziva se k potlaceni dvojitych 'new' alertu (Sauto + DE na to same auto).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Listing

MILEAGE_TOL_KM = 3_000  # najezd se smi lisit max o tolik (datova nepresnost)
PRICE_TOL = 0.08  # cena se smi lisit max o 8 %


def _similar(a: int, b: int, tol_pct: float) -> bool:
    hi = max(abs(a), abs(b))
    return hi == 0 or abs(a - b) / hi <= tol_pct


def same_car(a: Listing, b: Listing) -> bool:
    """Jsou to nejspis dva inzeraty toho sameho vozu?"""
    if a.year is None or a.mileage_km is None or b.year is None or b.mileage_km is None:
        return False
    return (
        a.model == b.model
        and a.generation == b.generation
        and a.year == b.year
        and abs(a.mileage_km - b.mileage_km) <= MILEAGE_TOL_KM
        and _similar(a.price_czk, b.price_czk, PRICE_TOL)
    )


def find_db_duplicate(session: Session, listing: Listing) -> Listing | None:
    """Najde aktivni inzerat z JINEHO zdroje, ktery je nejspis to same auto."""
    if listing.year is None or listing.mileage_km is None:
        return None

    candidates = session.scalars(
        select(Listing).where(
            Listing.id != listing.id,
            Listing.source != listing.source,
            Listing.is_active.is_(True),
            Listing.model == listing.model,
            Listing.generation == listing.generation,
            Listing.year == listing.year,
        )
    ).all()

    for cand in candidates:
        if same_car(cand, listing):
            return cand
    return None
