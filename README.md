# 🏁 Car Deal Hunter

Osobní nástroj, který hlídá inzeráty ojetých aut na víc portálech, ukládá historii
cen, **boduje každou nabídku vůči trhu** a pošle **push na Telegram**, když naskočí
dobrý deal nebo když existující inzerát zlevní.

Hlídané vozy (výchozí): **BMW 130i (E87)**, **Audi S3 (8P)**, **VW Golf GTI (Mk7)**.
Preference do skóre: manuál, RWD/AWD, nízký nájezd, rozpočet 200–300k Kč.

> Detailní kontext a rozhodnutí jsou v [`CLAUDE.md`](./CLAUDE.md) a ve
> [spec dokumentu](./docs/superpowers/specs/2026-06-18-car-deal-hunter-design.md).

---

## Jak to funguje

```
watch (model+generace) → scraper(y) → normalize → DB (Listing + PriceHistory)
   → diff (new / price-drop) → scoring vůči trhu → Telegram alert (anti-spam)
```

- **Scrapery** jsou pluginy (`app/scrapers/*.py`), každý portál = jeden modul.
  Funkční: **Sauto** (interní JSON API). Best-effort: **AutoScout24**, **Mobile.de**
  (DE portály, chráněné Cloudflarem — z cloud IP občas padají, výchozí vypnuté).
- **Scoring** (`app/scoring/engine.py`): lineární regrese `cena ~ rok + km` (numpy),
  bonusy za manuál / nízký nájezd / RWD-AWD. Při < 8 vzorcích fallback na medián.
- **Dashboard** (`web/`): React + TS + Vite, žebříček dealů + graf vývoje cen.

---

## Lokální vývoj

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -e ".[dev]"
copy .env.example .env        # vyplň (lokálně stačí SQLite default)

# jeden běh pipeline (to samé co spouští cron):
python -m app.run_once

# read API pro dashboard:
uvicorn app.main:app --reload     # http://127.0.0.1:8000

# dashboard:
cd web && npm install && npm run dev   # http://localhost:5173

# testy:
pytest
```

Lokálně se používá **SQLite** (`local.db`). Telegram je ve výchozím stavu
**dry-run** (`NOTIFY_ENABLED=false`) — alerty se jen logují, nic se neposílá.

### Užitečné scripty

```bash
# Naplní DB demo daty → uvidíš dashboard hned, bez scrapování/Neonu:
python -m scripts.seed_demo

# Vytáhne tvůj Telegram chat_id (nejdřív napiš botovi v Telegramu):
python -m scripts.telegram_chatid          # token z .env, nebo předej argumentem
```

> Za firemní TLS proxy, která láme SSL, nastav v `.env` `SSL_VERIFY=false`
> (v produkci nech `true`).

### Mobile.de (volitelné)

```bash
pip install -e ".[playwright]"
python -m playwright install chromium
```

A do `app/config.py` k danému watchi doplnit `portal_params["mobilede"]`.

---

## Telegram (jednorázově)

1. V Telegramu napiš `@BotFather` → `/newbot` → dostaneš `TELEGRAM_BOT_TOKEN`.
2. Napiš svému botovi cokoliv, pak otevři
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → vyčti svoje `chat.id`.
3. Vyplň `.env` a nastav `NOTIFY_ENABLED=true`.

---

## Deploy

| Co        | Kde                | Jak                                                  |
|-----------|--------------------|------------------------------------------------------|
| Scraper   | GitHub Actions cron| `.github/workflows/hunt.yml` (`*/30 * * * *`)        |
| DB        | Neon (Postgres)    | `DATABASE_URL` do GitHub Secrets i Vercel env        |
| Dashboard | Vercel             | `vercel.json` builduje `web/`, `api/index.py` čte DB |

**GitHub Secrets** (Settings → Secrets and variables → Actions):
`DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Repo je **public** kvůli
free minutám — proto **nikdy žádné secrets v kódu**.

`DATABASE_URL` pro Neon: `postgresql+psycopg://user:pass@host/db`.

---

## Konfigurace watchů

Vše v [`app/config.py`](./app/config.py) → `WATCHES`. Přidání vozu = jeden `Watch`
s `portal_params` (pro Sauto stačí `model_seo` ve tvaru `"značka:model"` + filtry).

---

## Pozn. k lokálnímu SSL

Pokud lokálně padá `CERTIFICATE_VERIFY_FAILED` (firemní proxy/AV, který odposlouchává
TLS), nejde o chybu scraperu — z čisté sítě a z GitHub Actions to běží. Případně
nastav `SSL_CERT_FILE` na firemní CA bundle.

---

## Struktura

```
app/        # jádro: scrapery, normalizace, pipeline, scoring, notify, API
web/        # React dashboard (Vercel)
api/        # Vercel serverless entrypoint (FastAPI read API)
tests/      # pytest (parsery, scoring, pipeline diff)
.github/    # cron workflow
```

Postaveno po krocích dle roadmapy v `CLAUDE.md §11`.
