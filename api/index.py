"""Vercel serverless entrypoint — read-only API pro dashboard.

Vercel (@vercel/python) obsluhuje ASGI aplikaci exportovanou jako `app`.
Cte z Neonu pres DATABASE_URL z Vercel env (NIKDY ne do frontendu).

Pozn.: pipeline/zapis bezi v GitHub Actions, tahle funkce jen cte.
"""

import sys
from pathlib import Path

# Zpristupni balicek app/ z korene repa.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

__all__ = ["app"]
