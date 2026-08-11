"""
api/main.py — FastAPI-приложение: REST API поверх Postgres + статика Mini App.

Запуск: uvicorn api.main:app --host 0.0.0.0 --port $PORT (из корня репозитория —
нужно, чтобы `database.py` в корне был импортируем как `import database`).
"""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

import database as db
from api.routers import export, family, stats, treatments, walks

MINIAPP_DIR = Path(__file__).resolve().parent.parent / "miniapp"

# Без этого INFO-логи (в т.ч. таймер запросов ниже и DB_TIMING_LOG в database.py)
# нигде не появляются — uvicorn настраивает логирование только для своих
# собственных логгеров ("uvicorn"/"uvicorn.access"), не для корневого/нашего.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("barbos.timing")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Barbos API", lifespan=lifespan)


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    """Диагностика долгой загрузки Mini App: серверное время обработки запроса
    (включая все db.*-вызовы внутри хендлера). Сравнение с временем, которое
    видит браузер в Network tab, показывает, где теряется время — в сети/на
    подъём Railway-контейнера после простоя, или в самом FastAPI/Postgres."""
    started = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - started) * 1000
    logger.info("%s %s -> %s (%.1f ms)", request.method, request.url.path, response.status_code, duration_ms)
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
    return response


@app.get("/health")
def health():
    """Не трогает БД специально — цель чисто в том, чтобы процесс ответил и
    Railway (или внешний keep-warm пинг) не считал контейнер уснувшим.
    Проверка живости самого Postgres/пула тут не нужна и не является целью."""
    return {"status": "ok"}


# Роутеры регистрируются раньше статики — иначе catch-all StaticFiles("/")
# перехватывал бы запросы к /api/* раньше, чем до них доходит очередь.
app.include_router(family.router)
app.include_router(walks.router)
app.include_router(treatments.router)
app.include_router(stats.router)
app.include_router(export.router)

app.mount("/", StaticFiles(directory=MINIAPP_DIR, html=True), name="miniapp")
