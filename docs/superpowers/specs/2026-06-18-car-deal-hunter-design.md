# Car Deal Hunter — Design Spec

> Datum: 2026-06-18. Vychází z `CLAUDE.md`. Tenhle dokument je závazný spec pro implementaci celého projektu najednou.

## Cíl

Osobní nástroj, který hlídá inzeráty ojetých aut na víc portálech, ukládá historii cen, boduje každou nabídku vůči trhu a pošle push na Telegram při dobrém dealu nebo zlevnění. Není to seznam aut — je to alert engine.

Výchozí watche: BMW 130i (E87), Audi S3 (8P), VW Golf GTI (Mk7). Preference: manuál, RWD/AWD, 200–300k Kč, nízký nájezd.

## Klíčová technická rozhodnutí

- **Sync** všude (httpx.Client, sync SQLAlchemy 2.x). Async se přidá až bude úzké hrdlo.
- **DB:** SQLite lokálně (`local.db`) přes `DATABASE_URL`, default `sqlite:///local.db`. Neon (Postgres) v produkci přes stejnou proměnnou — kód agnostický k dialektu.
- Type hints všude, `ruff` + `black`. Žádné secrets v kódu (repo public) — vše přes env.
- Scrapery padají hlasitě (log + raise při změně struktury), ne tiše prázdno.

## Architektura

```
app/
├── config.py        # Settings (pydantic-settings) + WATCHES (watch listy)
├── db.py            # engine, SessionLocal, init_db()
├── models.py        # Base, Listing, PriceHistory, Alert
├── normalize.py     # RawListing -> Listing dict; parsování textů na enumy/čísla
├── fx.py            # EUR->CZK kurz (ČNB), cache na den
├── scrapers/
│   ├── base.py      # Scraper ABC, RawListing, SearchQuery
│   ├── sauto.py     # JSON API
│   ├── autoscout24.py  # JSON + hlavičky
│   └── mobilede.py  # Playwright (best-effort, padá měkce)
├── scoring/
│   └── engine.py    # lineární regrese cena~rok+km, deal score, fallback medián
├── notify/
│   └── telegram.py  # send_message + format_alert
├── pipeline.py      # orchestrace jednoho běhu
├── run_once.py      # entrypoint pro cron
└── main.py          # FastAPI: ruční trigger + read API pro dashboard
tests/
web/                 # React/TS/Vite dashboard
.github/workflows/hunt.yml
```

## Datový model (§6 CLAUDE.md)

- **Listing**: id, source, source_id, model, generation, year, mileage_km, transmission(manual/auto), drivetrain(rwd/awd/fwd), price_czk, price_original, currency, url, title, first_seen, last_seen, is_active. Unikát `(source, source_id)`.
- **PriceHistory**: id, listing_id(fk), price_czk, seen_at.
- **Alert**: id, listing_id(fk), kind(new/price_drop), score, sent_at.

## Komponenty

### Scraper rozhraní (`scrapers/base.py`)
```python
@dataclass
class SearchQuery: model: str; generation: str; params: dict
@dataclass
class RawListing: source: str; source_id: str; title: str; url: str;
                  price: int; currency: str; year: int|None;
                  mileage_km: int|None; raw: dict
class Scraper(ABC):
    name: str
    def fetch_listings(self, query: SearchQuery) -> list[RawListing]: ...
```
- Realistické hlavičky, random delay 3–8 s mezi requesty, max pár stránek/běh.

### Normalizér (`normalize.py`)
- RawListing -> dict pro Listing. Mapuje převodovku/pohon na enum, parsuje rok/km/cenu, převádí EUR->CZK přes `fx`. Detekuje model+generaci (u DE portálů z titulku).

### Pipeline (`pipeline.py`)
Pro každý watch × scraper: fetch (try/except per scraper, jeden padne → ostatní jedou) → normalize → upsert (insert nový + PriceHistory; existující update last_seen, při změně ceny append PriceHistory) → detect new/price-drop → score → pokud `score >= threshold` a ještě nealertováno → telegram.send + zapiš Alert. Inzeráty co zmizely z portálu → `is_active=False`.

### Scoring (`scoring/engine.py`)
- Per model+generace rolling dataset aktivních listingů.
- Odhad ceny: lineární regrese `cena ~ rok + km` (numpy lstsq, bez scikit-learn dependency).
- Deal score = % pod predikcí + bonus za manuál / nízký km vůči ročníku / RWD-AWD.
- Málo dat (< 8 vzorků): fallback na medián, případně jen "nový inzerát v rozpočtu". Práh konfigurovatelný (`DEAL_THRESHOLD`, default 0.10).

### Notifier (`notify/telegram.py`)
- `send_message(text)` přes Bot API (httpx POST, ne celý python-telegram-bot — jen send). Token/chat_id z env. `format_alert(listing, score, kind)` → Markdown s emoji, odkaz. Anti-spam přes tabulku Alert.

### FX (`fx.py`)
- ČNB denní kurz endpoint, cache na den (in-memory + soubor). EUR->CZK.

### Dashboard (`web/`)
- React + TS + Vite, tabulka dle deal score, graf cen (Recharts), filtry. Čte `/api/listings` (FastAPI lokálně / Vercel serverless v prod). Connection string nikdy ve frontendu.

## Pořadí implementace (roadmapa §11)
1. Kostra: pyproject, model, db, config, Sauto → `run_once` plní DB.
2. Historie + diff: PriceHistory, upsert, detekce new/price-drop.
3. Telegram: notifier + formát + anti-spam.
4. Scoring: regrese + deal score + fallback.
5. AutoScout24 scraper.
6. Mobile.de scraper (Playwright, měkké pády).
7. Dashboard.
8. Deploy: GitHub Actions cron, .env.example, README.

Každý krok musí reálně běžet, než jdu na další.

## Testování
- Unit: normalizér (parsování ceny/km/rok z textu), scoring (regrese + fallback), pipeline diff (new/price-drop) s in-memory SQLite.
- Scrapery: proti uloženým JSON sample fixtures, žádná síť v testech.
- Live smoke test Sauto scraperu mimo CI (ruční), protože závisí na reálném API.

## Známá rizika (§8)
- GitHub Actions IP → Cloudflare blok (Mobile.de bude padat z cloudu) → měkké pády.
- Změny struktury portálů → scrapery padají hlasitě.
- Free DB 0.5 GB → retention na PriceHistory (později).

## Co NEřešíme teď
- Residential proxy, self-hosted runner, pokročilejší ML model, autentizace dashboardu, retention cron. Až bude potřeba.
