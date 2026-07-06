# 🏁 Car Deal Hunter

Osobní nástroj, který hlídá inzeráty ojetých aut na **CZ i DE bazarech** (Sauto,
Sbazar, AutoScout24), ukládá historii cen, **boduje každou nabídku vůči trhu**
a pošle **email/Telegram**, když naskočí dobrý deal nebo inzerát zlevní.

**Hlídat jde libovolné auto** — přidává se přímo ve webu („+ Přidat auto":
značka, model, varianta, roky, cena) nebo natvrdo v `app/config.py`.
Výchozí: BMW 130i (E87), Audi S3 (8P), VW Golf GTI (Mk7).

> Detailní kontext a rozhodnutí jsou v [`CLAUDE.md`](./CLAUDE.md) a ve
> [spec dokumentu](./docs/superpowers/specs/2026-06-18-car-deal-hunter-design.md).

---

## Jak to funguje

```
watch (config + web garáž) → scrapery → normalize → DB (Listing + PriceHistory)
   → diff (new / price-drop) → scoring vůči trhu → email/Telegram alert (anti-spam)
```

- **Scrapery** jsou pluginy (`app/scrapers/*.py`), každý portál = jeden modul.
  Funkční: **Sauto**, **Sbazar** (JSON API), **AutoScout24.de** (`__NEXT_DATA__`).
  **Mobile.de** je blokovaný Akamaiem i lokálně — vyžadoval by residential proxy;
  německý trh pokrývá AutoScout24. Facebook Marketplace zatím není (login + ban riziko).
- **Scoring** (`app/scoring/engine.py`): lineární regrese `cena ~ rok + km` (numpy),
  bonusy za manuál / nízký nájezd / RWD-AWD. Při < 8 vzorcích fallback na medián.
- **Dashboard** (`web/`): React + TS + Vite — fulltext („golf gti 2013 manual"),
  filtry (palivo, rok, cena, zdroj), fotkové karty, sloučení stejného auta z víc
  bazarů, graf vývoje cen, správa garáže.

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

### Mobile.de — denní lokální běh (zdarma, z domácí IP)

Mobile.de chrání Akamai: z cloudu neprůchodné, z domácí (rezidenční) IP přes
Firefox to projde. Proto běží 1× denně **lokálně na tvém Macu** a zapisuje do
stejné DB jako cron:

```bash
pip install -e ".[playwright]"
python -m playwright install firefox

# rucni test (pri Akamai challenge mekce skonci, zkus jindy):
python -m scripts.run_mobilede_local

# automaticky kazdy den v 8:15 (jednorazova instalace):
cp deploy/com.carscout.mobilede.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.carscout.mobilede.plist
# log: /tmp/carscout-mobilede.log
```

Parametry si odvodí z watchů automaticky. Diagnostika: `python -m scripts.mobilede_probe`
(jediný opatrný pokus; při úspěchu uloží snapshot stránky). Pozor: opakované
pokusy Akamai flag prodlužují — max pár za den.

---

## Telegram (jednorázově)

1. V Telegramu napiš `@BotFather` → `/newbot` → dostaneš `TELEGRAM_BOT_TOKEN`.
2. Napiš svému botovi cokoliv, pak otevři
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → vyčti svoje `chat.id`.
3. Vyplň `.env` a nastav `NOTIFY_ENABLED=true`.

---

## Deploy (vše zdarma)

Architektura: **Neon** (Postgres, sdílená DB) ← **GitHub Actions** (scrapuje každou
hodinu) → **Vercel** (web + read/watch API).

**1. Neon (databáze, ~5 min)**
1. [neon.tech](https://neon.tech) → registrace → New project (region EU).
2. Zkopíruj connection string a uprav schéma na:
   `postgresql+psycopg://user:pass@host/db?sslmode=require`
   (bez uvozovek, bez `psql` na začátku — kód běžné překlepy opraví sám).

**2. GitHub Secrets (scraping + email, ~5 min)**
Repo → Settings → Secrets and variables → Actions → New repository secret:
- `DATABASE_URL` — Neon string z kroku 1
- `SMTP_USER` — tvůj Gmail
- `SMTP_PASSWORD` — Gmail **App password** (Google účet → Security → 2FA → App passwords)
- `EMAIL_TO` — kam posílat alerty
- volitelně `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (+ Actions Variable `NOTIFY_ENABLED=true`)

Pak Actions → hunt → **Run workflow** (první ostrý běh naplní Neon).

**3. Vercel (web, ~5 min)**
1. [vercel.com](https://vercel.com) → Add New Project → Import z GitHubu (`auto_scout`).
2. Nastavení projektu → Environment Variables → přidej `DATABASE_URL` (stejný Neon string).
3. Deploy. `vercel.json` builduje `web/`, `api/index.py` obsluhuje `/api/*` z Neonu.

Repo je **public** kvůli free minutám — proto **nikdy žádné secrets v kódu**.

Pozn.: tlačítko „Prohledat teď" funguje jen lokálně (Vercel serverless nemůže
scrapovat — timeout). Na webu se nové auto prohledá při dalším cron běhu (do hodiny).

---

## Konfigurace watchů

**Web**: tlačítko „+ Přidat auto" (značka, model, varianta, roky, cena) — uloží se
do DB (tabulka `watches`), cron ho pak automaticky prohledává na všech portálech.
Dotazy pro portály staví [`app/watch_builder.py`](./app/watch_builder.py).

**Kód**: kurátorské watche v [`app/config.py`](./app/config.py) → `WATCHES`
(plná kontrola nad portal_params, např. `power_from_kw` pro BMW 130i).

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
