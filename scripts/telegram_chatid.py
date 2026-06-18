"""Vytahne tvuj Telegram chat_id, at nelovis v JSONu z getUpdates.

Pouziti:
    1) Napis svemu botovi v Telegramu cokoliv (treba "ahoj").
    2) Spust:  python -m scripts.telegram_chatid           # token vezme z .env
       nebo:   python -m scripts.telegram_chatid <TOKEN>

Vypise vsechny chaty, ze kterych bot dostal zpravu, vc. chat_id.
"""

from __future__ import annotations

import sys

import httpx

from app.config import settings


def main() -> int:
    token = sys.argv[1] if len(sys.argv) > 1 else settings.telegram_bot_token
    if not token:
        print("Chybi token. Predej ho jako argument nebo nastav TELEGRAM_BOT_TOKEN v .env.")
        return 1

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    resp = httpx.get(url, timeout=15.0, verify=settings.ssl_verify)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        print("Telegram vratil chybu:", data)
        return 1

    updates = data.get("result", [])
    if not updates:
        print("Zadne zpravy. Nejdriv napis svemu botovi v Telegramu, pak spust znovu.")
        return 1

    seen: dict[int, str] = {}
    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is not None and cid not in seen:
            name = chat.get("title") or chat.get("username") or chat.get("first_name") or "?"
            seen[cid] = f"{name} ({chat.get('type', '?')})"

    print("Nalezene chaty:")
    for cid, label in seen.items():
        print(f"  TELEGRAM_CHAT_ID={cid}   # {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
