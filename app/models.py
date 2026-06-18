"""SQLAlchemy modely: Listing, PriceHistory, Alert."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_source_sourceid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # sauto | mobilede | autoscout24
    source_id: Mapped[str] = mapped_column(String(128))

    model: Mapped[str] = mapped_column(String(32), index=True)  # bmw_130i | audi_s3 | golf_gti
    generation: Mapped[str] = mapped_column(String(16))  # e87 | 8p | mk7

    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mileage_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transmission: Mapped[str | None] = mapped_column(String(16), nullable=True)  # manual | auto
    drivetrain: Mapped[str | None] = mapped_column(String(16), nullable=True)  # rwd | awd | fwd

    price_czk: Mapped[int] = mapped_column(Integer)
    price_original: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8))  # CZK | EUR

    url: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(256))

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    price_history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    price_czk: Mapped[int] = mapped_column(Integer)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    listing: Mapped["Listing"] = relationship(back_populates="price_history")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # new | price_drop
    score: Mapped[float] = mapped_column(Float)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    listing: Mapped["Listing"] = relationship(back_populates="alerts")
