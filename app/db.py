"""SQLAlchemy engine + session factory. Agnosticke k SQLite/Postgres."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base

logger = logging.getLogger(__name__)

# SQLite chce check_same_thread=False kvuli pripadnemu sdileni napric vlakny.
_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# Sloupce pridane po prvnim nasazeni — lehka migrace (create_all neresi ALTER).
# (nazev sloupce, SQL typ) pro tabulku listings.
_ADDED_COLUMNS = {
    "image_url": "VARCHAR(512)",
    "fuel_type": "VARCHAR(16)",
    "power_kw": "INTEGER",
    "body_type": "VARCHAR(16)",
}


def _ensure_columns() -> None:
    """Doplni chybejici sloupce do existujici tabulky listings (SQLite i Postgres).

    create_all() nove sloupce do uz existujici tabulky neprida — u DB, ktera
    vznikla drive (napr. Neon v produkci), by pak dotazy padaly. Tohle je bezpecne
    (ADD COLUMN IF NOT EXISTS logika pres inspektor), bezi pri kazdem startu.
    """
    inspector = inspect(engine)
    if "listings" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("listings")}
    with engine.begin() as conn:
        for name, sql_type in _ADDED_COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE listings ADD COLUMN {name} {sql_type}"))
                logger.info("migrace: pridan sloupec listings.%s", name)


def init_db() -> None:
    """Vytvori tabulky, pokud jeste neexistuji, a doplni chybejici sloupce."""
    Base.metadata.create_all(engine)
    _ensure_columns()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transakcni kontext: commit pri uspechu, rollback pri vyjimce."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
