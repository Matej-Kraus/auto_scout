# 🚀 Nasazení na internet — checklist

Odškrtávej postupně. Celé ~15 min, vše zdarma. Podrobnosti v `README.md`.

## ☐ 1. Neon — databáze (~5 min)
1. [neon.tech](https://neon.tech) → Sign up (klidně přes GitHub).
2. **Create project** → region **Frankfurt (eu-central-1)**.
3. **Connect** → zkopíruj `postgresql://…` string (kód si formát opraví sám).

## ☐ 2. GitHub Secrets — scraping (~2 min)
Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Name | Value |
|------|-------|
| `DATABASE_URL` | Neon string z kroku 1 |

> Email je vypnutý (web je hlavní rozhraní). Pokud bys ho někdy chtěl, přidej
> `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` + Actions Variable `EMAIL_ENABLED=true`.

Pak **Actions → hunt → Run workflow** (první ostrý běh naplní Neon).

## ☐ 3. Vercel — web na netu (~5 min)
1. [vercel.com](https://vercel.com) → Sign up (přes GitHub) → **Add New… → Project**.
2. Import repozitáře **auto_scout**.
3. **Environment Variables** → přidej `DATABASE_URL` = stejný Neon string.
4. **Deploy**. Za ~2 min máš veřejnou URL.

## ☐ 4. Mobile.de — denní běh z domácí IP (volitelné, ~2 min)
Až Akamai flag vyprchá (netestuj opakovaně!):
```bash
python -m scripts.mobilede_probe        # když napíše ÚSPĚCH, pokračuj:
cp deploy/com.carscout.mobilede.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.carscout.mobilede.plist
```

---

Hotovo → web běží veřejně, cron plní DB každou hodinu, mobile.de jednou denně.
Auta ze všech bazarů v jednom srovnaném žebříčku.
