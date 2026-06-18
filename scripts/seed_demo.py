"""Naplni DB realisticky vypadajicimi demo inzeraty + historii cen.

Slouzi k nahledu dashboardu bez scrapovani / Neonu:

    python -m scripts.seed_demo
    uvicorn app.main:app --reload
    cd web && npm run dev

Demo zaznamy maji source="demo", takze je poznas a snadno smazes.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal, init_db
from app.models import Listing, PriceHistory

random.seed(42)

# (model, generace, label, zakladni cena, rozptyl km)
SPECS = [
    ("bmw_130i", "e87", "BMW 130i", 240_000, "rwd"),
    ("audi_s3", "8p", "Audi S3", 250_000, "awd"),
    ("golf_gti", "mk7", "VW Golf GTI", 300_000, "fwd"),
]
TITLES = {
    "bmw_130i": ["BMW Řada 1, 130i 195kW", "BMW 130i M-Paket manuál", "BMW 130i sport"],
    "audi_s3": ["Audi S3 2.0 TFSI quattro", "Audi S3 8P S-Line", "Audi S3 Sportback quattro"],
    "golf_gti": ["VW Golf GTI 2.0 TSI", "Golf GTI Performance DSG", "Golf 7 GTI manuál"],
}


def main() -> None:
    init_db()
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        session.query(Listing).filter(Listing.source == "demo").delete()
        session.flush()

        n = 0
        for model, gen, _label, base, drive in SPECS:
            for i in range(8):
                year = random.randint(2007, 2018)
                km = random.randint(80_000, 230_000)
                # cena klesa s km a roste s rokem + sum; nektere podhodnocene = dealy
                price = int(base - (km - 120_000) * 0.6 + (year - 2010) * 6000)
                price += random.randint(-45_000, 25_000)
                price = max(120_000, price)
                transmission = random.choice(["manual", "manual", "auto"])
                first_seen = now - timedelta(hours=random.randint(1, 240))

                listing = Listing(
                    source="demo",
                    source_id=f"{model}-{i}",
                    model=model,
                    generation=gen,
                    year=year,
                    mileage_km=km,
                    transmission=transmission,
                    drivetrain=drive,
                    price_czk=price,
                    price_original=price,
                    currency="CZK",
                    url="https://www.sauto.cz/",
                    title=random.choice(TITLES[model]),
                    first_seen=first_seen,
                    last_seen=now,
                    is_active=True,
                )
                session.add(listing)
                session.flush()

                # historie: par bodu, obcas zlevneni
                p = price + random.randint(0, 40_000)
                for d in range(random.randint(1, 4)):
                    session.add(
                        PriceHistory(
                            listing_id=listing.id,
                            price_czk=p,
                            seen_at=first_seen + timedelta(days=d * 7),
                        )
                    )
                    p = max(price, p - random.randint(0, 15_000))
                session.add(PriceHistory(listing_id=listing.id, price_czk=price, seen_at=now))
                n += 1

        session.commit()
    print(f"Naseedovano {n} demo inzeratu. Spust uvicorn + web a koukni na dashboard.")


if __name__ == "__main__":
    main()
