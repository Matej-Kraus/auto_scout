# CLAUDE.md — Car Deal Hunter

> Kontext pro Claude Code. Přečti celý před prací na projektu.

---

## 0. Komunikace (DŮLEŽITÉ)

- S uživatelem komunikuj **česky, neformálně a stručně**. Žádné zbytečné caveaty.
- Praktické příklady > teorie. Konkrétní doporučení > abstraktní úvahy.
- Když je něco blbý nápad, řekni to rovnou.
- Komentáře v kódu a názvy identifikátorů anglicky (konvence). Texty pro uživatele (Telegram zprávy, UI) klidně česky.

---

## 1. Co to je

Osobní nástroj, který **hlídá inzeráty ojetých aut** na víc portálech, ukládá historii cen,
**boduje každou nabídku vůči trhu** a pošle **push na Telegram**, když naskočí dobrý deal
nebo když existující inzerát zlevní.

Cíl není mít "seznam 200 aut", ale dostat zprávu typu:

> 🔥 Audi S3 8P · 2011 · 140 000 km · 215 000 Kč
> 22 % pod mediánem srovnatelných · manuál · quattro · naskočilo před 2 h
> https://...

Tohle je osobní projekt na vlastní použití (hledání víkendovky). Není to komerční scraper na prodej dat.

---

## 2. Hledané vozy (výchozí watche)

Tyhle natvrdo jako default watch listy. Uživatel si je pak může v configu upravit.

| Model            | Generace | Pozn.                         |
|------------------|----------|-------------------------------|
| BMW 130i         | E87      | RWD, řadová šestka, zvuk      |
| Audi S3          | 8P       | AWD (quattro)                 |
| VW Golf GTI      | Mk7      | FWD                           |

**Společné preference (= vstup do skóre, bonusové body):**
- Převodovka: **manuál** (silná preference)
- Pohon: **RWD nebo AWD** preferováno
- Rozpočet: **200 000 – 300 000 Kč**
- Nízký nájezd = plus
- Dobrý zvuk motoru = subjektivní, neřeší se algoritmicky

---

## 3. Stack

| Vrstva       | Volba                                   | Proč                                  |
|--------------|------------------------------------------|---------------------------------------|
| Backend/jádro| **Python 3.12 + FastAPI**                | Co uživatel umí                       |
| ORM          | **SQLAlchemy 2.x**                        | Co uživatel umí                       |
| DB           | **Neon (serverless Postgres)** / lokálně SQLite | Free tier, scale-to-zero        |
| HTTP scrape  | **httpx**                                 | Async, rychlé                         |
| Tvrdé portály| **Playwright** (headless Chromium)        | Cloudflare na Mobile.de               |
| Scheduler    | **GitHub Actions cron** (prod) / APScheduler (lokál) | Free, žádný 24/7 server      |
| Notifikace   | **python-telegram-bot** (jen send)        | Push na mobil zdarma                  |
| Frontend     | **React + TypeScript + Vite**             | Co uživatel umí                       |
| Grafy        | **Recharts**                              | Vývoj cen                             |
| Dashboard host| **Vercel** (free)                        | Statika + 1 serverless read endpoint  |

---

## 4. Architektura

### 4.1 Plugin scrapery (srdce rozšiřitelnosti)

Každý portál = jeden modul implementující společné rozhraní. Přidání dalšího portálu = jeden nový soubor, nic jiného se nemění.

```python
# scrapers/base.py
from abc import ABC, abstractmethod

class Scraper(ABC):
    name: str  # "sauto", "mobilede", "autoscout24"

    @abstractmethod
    async def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        """Stáhne a vrátí surové inzeráty pro daný dotaz."""
        ...
```

- `scrapers/sauto.py` — **začni tímhle**. Sauto má interní JSON API
  (frontend si tahá data z endpointů typu `/api/v1/items/...`), takže žádné parsování HTML,
  jen čistý JSON → nejrychlejší cesta k prvním datům v DB.
- `scrapers/autoscout24.py` — JSON endpointy, ale chráněnější. httpx + realistické hlavičky.
- `scrapers/mobilede.py` — nejtvrdší (Cloudflare). Playwright. Počítej s tím, že z cloud IP
  (GitHub Actions) bude občas padat — viz §8.

Scrapery vrací `RawListing` (syrová data), normalizér je převede na `Listing` (čistý model).
Normalizace řeší: parsování ceny/nájezdu/roku z textu, mapování převodovky a pohonu na enum,
detekci modelu+generace.

### 4.2 Pipeline (jeden běh)

```
for each watch (model+generace):
    for each scraper:
        raw = scraper.fetch_listings(query)     # síť
    normalized = normalize(raw)                  # čištění
    upsert do DB (Listing, append PriceHistory)  # perzistence
    detect new / price-drop                      # diff vůči minulému stavu
    score = scoring_engine.score(listing)        # skóre vůči trhu
    if score >= threshold and not already_alerted:
        telegram.send(format_alert(listing, score))
        record Alert
```

### 4.3 Scoring engine (= wow efekt)

`scoring/engine.py`

1. Pro každý model+generaci drž rolling dataset všech viděných inzerátů.
2. Odhadni očekávanou cenu — **start: jednoduchá lineární regrese** `cena ~ rok + km`
   (scikit-learn nebo ručně přes numpy). Až bude dat dost, klidně něco chytřejšího.
3. **Deal skóre** = jak moc je inzerát pod předpovězenou cenou (v %), plus bonus:
   - `+` za manuál
   - `+` za nízký nájezd vůči ročníku
   - `+` za RWD/AWD
4. Práh pro alert konfigurovatelný (default např. ≥ 10 % pod predikcí).

Pozor na málo dat: dokud je v datasetu pro daný model < N vzorků (např. 8),
**neposílej skóre založené na regresi** — fallback na medián, nebo jen "nový inzerát v rozpočtu".

### 4.4 Notifier

`notify/telegram.py` — jen `send_message`. Token a chat_id z env (viz §7).
Formátování zprávy hezky (emoji, tučně přes Markdown), odkaz na inzerát.
Anti-spam: tabulka `Alert` drží, co už odešlo, ať nechodí ten samý inzerát dokola.

### 4.5 Dashboard

`web/` — React/TS/Vite. Tabulka inzerátů seřazená podle deal skóre, graf vývoje cen (Recharts),
filtry. Čte data z Neonu přes jednu serverless funkci na Vercelu
(read-only endpoint `/api/listings`). **Connection string nikdy do frontendu** — jen do serverless funkce z env.

---

## 5. Struktura repa

```
car-deal-hunter/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .github/
│   └── workflows/
│       └── hunt.yml            # cron job
├── app/
│   ├── main.py                 # FastAPI (lokální API + ruční trigger)
│   ├── run_once.py             # entrypoint pro 1 běh pipeline (volá ho cron)
│   ├── config.py               # watch listy, prahy, env
│   ├── db.py                   # SQLAlchemy engine/session
│   ├── models.py               # Listing, PriceHistory, Alert, SearchQuery
│   ├── normalize.py
│   ├── pipeline.py
│   ├── scrapers/
│   │   ├── base.py
│   │   ├── sauto.py
│   │   ├── autoscout24.py
│   │   └── mobilede.py
│   ├── scoring/
│   │   └── engine.py
│   └── notify/
│       └── telegram.py
├── tests/
└── web/                        # React dashboard (Vercel)
```

---

## 6. Datový model

```python
class Listing:
    id: int (pk)
    source: str               # "sauto" | "mobilede" | "autoscout24"
    source_id: str            # id inzerátu na portálu (pro upsert/dedup)
    model: str                # "bmw_130i" | "audi_s3" | "golf_gti"
    generation: str           # "e87" | "8p" | "mk7"
    year: int
    mileage_km: int
    transmission: str         # "manual" | "auto"
    drivetrain: str           # "rwd" | "awd" | "fwd"
    price_czk: int            # vždy převedeno na CZK (EUR×kurz u DE portálů)
    price_original: int       # původní částka
    currency: str             # "CZK" | "EUR"
    url: str
    title: str
    first_seen: datetime
    last_seen: datetime
    is_active: bool           # zmizel z portálu => False
    # unikátní index: (source, source_id)

class PriceHistory:
    id: int (pk)
    listing_id: int (fk)
    price_czk: int
    seen_at: datetime

class Alert:
    id: int (pk)
    listing_id: int (fk)
    kind: str                 # "new" | "price_drop"
    score: float
    sent_at: datetime
```

Kurz EUR→CZK: tahej z nějakého free API (ČNB má veřejný denní kurz endpoint) a cachuj na den.

---

## 7. Secrets / env

`.env.example`:
```
DATABASE_URL=postgresql+psycopg://...neon...
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DEAL_THRESHOLD=0.10
```

- Lokálně: `.env` (v `.gitignore`!).
- V GitHub Actions: **GitHub Secrets** (Settings → Secrets and variables → Actions).
  Workflow je čte přes `${{ secrets.X }}`. **Nikdy nehardcoduj do kódu** — repo je public.

**Telegram setup (jednorázově, ručně):**
1. V Telegramu napiš `@BotFather` → `/newbot` → dostaneš `TELEGRAM_BOT_TOKEN`.
2. Napiš svému botovi cokoliv, pak otevři
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → z odpovědi vyčti svoje `chat.id`.

---

## 8. Známé pasti (přečti, ušetří hodiny)

1. **GitHub Actions IP jsou cloudové → Cloudflare je blokuje.**
   Sauto a nejspíš AutoScout24 pojedou. **Mobile.de bude z Actions občas padat.**
   Pipeline to musí ustát (try/except per scraper, jeden zdroj selže → ostatní jedou dál).
   Pozdější řešení: residential proxy nebo self-hosted runner na Raspberry/VPS.
2. **Public repo + scheduled workflow se po 60 dnech neaktivity sám vypne.**
   Stačí občas pushnout commit, nebo přidat do workflow drobný "heartbeat" commit.
   Počítej s tím.
3. **Slušný scraping, ať tě nezablokujou hned:**
   - realistické `User-Agent` a hlavičky
   - random delay mezi requesty (3–8 s)
   - max pár stránek za běh
   - interval běhu rozumný (např. každých 20–30 min, ne každou minutu)
   Cílem je hlídat, ne portál zahltit.
4. **Neon scale-to-zero → cold start ~300–500 ms** u prvního dotazu. U cron jobu nevadí.
5. **Selektory/JSON struktura portálů se mění.** Scrapery musí padat hlasitě
   (log + případně Telegram "scraper X se rozbil"), ne tiše vracet prázdno.
6. **Free DB má 0.5 GB.** Stará neaktivní data občas archivuj/maž (retention na `PriceHistory`).

---

## 9. Lokální vývoj

```bash
# setup
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # vyplň

# lokálně klidně SQLite místo Neonu (DATABASE_URL=sqlite+aiosqlite:///local.db)

# jeden běh pipeline (to samé co spouští cron):
python -m app.run_once

# FastAPI (ruční trigger + lokální API pro dashboard):
uvicorn app.main:app --reload

# Playwright (jen poprvé):
playwright install chromium

# testy
pytest
```

---

## 10. Deploy

- **Scraper:** `.github/workflows/hunt.yml` s `on: schedule: - cron: "*/30 * * * *"`.
  Krok: checkout → setup-python → pip install → `playwright install chromium`
  → `python -m app.run_once`. Secrets z GitHub Secrets. Repo **public** (free minuty).
- **DB:** Neon projekt, connection string do secrets.
- **Dashboard:** `web/` na Vercel (free). Serverless funkce `/api/listings` čte z Neonu.

---

## 11. Roadmapa (pořadí prací)

1. **Kostra:** repo, `pyproject.toml`, datový model, `db.py`, config s watch listy. + Sauto scraper. Cíl: `run_once` ti hodí reálné inzeráty do DB.
2. **Historie + diff:** `PriceHistory`, upsert logika, detekce new / price-drop.
3. **Telegram:** notifier + formátování + anti-spam (`Alert`).
4. **Scoring:** regrese `cena ~ rok+km`, deal skóre, fallback na medián při málo datech.
5. **AutoScout24 scraper** (httpx + hlavičky).
6. **Mobile.de scraper** (Playwright) + ošetření pádů.
7. **Dashboard:** React/TS, tabulka podle skóre, graf cen.
8. **Deploy:** GitHub Actions cron, Neon, Vercel. Doladit intervaly a prahy.

Postupuj **po krocích, každý krok ať reálně běží**, než jdeš na další. Nestav všechno najednou.

---

## 12. Konvence

- Python: type hints všude, async kde to dává smysl (httpx, DB), `ruff` + `black`.
- Žádné tajnosti v kódu (repo je public) — vše citlivé přes env.
- Scrapery musí padat hlasitě, ne tiše.
- Commituj po funkčních celcích.
