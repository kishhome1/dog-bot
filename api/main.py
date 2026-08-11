"""
api/main.py — FastAPI-приложение: REST API поверх Postgres + статика Mini App.

Запуск: uvicorn api.main:app --host 0.0.0.0 --port $PORT (из корня репозитория —
нужно, чтобы `database.py` в корне был импортируем как `import database`).
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import database as db
from api.routers import family, stats, treatments, walks

MINIAPP_DIR = Path(__file__).resolve().parent.parent / "miniapp"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Barbos API", lifespan=lifespan)

# Роутеры регистрируются раньше статики — иначе catch-all StaticFiles("/")
# перехватывал бы запросы к /api/* раньше, чем до них доходит очередь.
app.include_router(family.router)
app.include_router(walks.router)
app.include_router(treatments.router)
app.include_router(stats.router)

app.mount("/", StaticFiles(directory=MINIAPP_DIR, html=True), name="miniapp")
