"""
api/auth.py — валидация Telegram WebApp initData и получение текущего участника семьи.

Алгоритм — по официальной документации Telegram ("Validating data received via
the Mini App"): пересчитываем HMAC-SHA256 по отсортированным key=value парам
initData и сверяем со значением поля hash. Клиент присылает сырой initData
в заголовке `Authorization: tma <initData>`.
"""

import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from fastapi import Depends, Header, HTTPException

import database as db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# initData Telegram подписывает при каждом открытии Mini App — если она старше
# суток, что-то не так (например, протухшая закешированная ссылка), просим переоткрыть.
MAX_INIT_DATA_AGE_SECONDS = 24 * 3600


def _validate_init_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="BOT_TOKEN не настроен на сервере")

    try:
        data = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        raise HTTPException(status_code=401, detail="Не удалось разобрать initData")

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="initData без hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise HTTPException(status_code=401, detail="Невалидная подпись initData")

    auth_date = data.get("auth_date")
    if auth_date and time.time() - int(auth_date) > MAX_INIT_DATA_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="initData устарела, откройте Mini App заново")

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="initData без user")

    user = json.loads(user_raw)
    return {
        "tg_user_id": user["id"],
        "display_name": user.get("first_name") or user.get("username") or "Без имени",
    }


def get_telegram_user(authorization: str = Header(...)) -> dict:
    """Достаёт и валидирует initData из заголовка Authorization. Не требует
    существующего членства в семье — используется онбордингом (/api/auth,
    /api/family, /api/family/join)."""
    scheme, _, init_data = authorization.partition(" ")
    if scheme.lower() != "tma" or not init_data:
        raise HTTPException(
            status_code=401,
            detail="Ожидается заголовок Authorization: tma <initData>",
        )
    return _validate_init_data(init_data)


def get_current_member(user: dict = Depends(get_telegram_user)) -> dict:
    """Требует, чтобы пользователь уже состоял в семье — зависимость для всех
    защищённых эндпоинтов (walks/treatments/stats)."""
    member = db.get_member_by_tg_user_id(user["tg_user_id"])
    if member is None:
        raise HTTPException(status_code=404, detail="Пользователь ещё не состоит в семье")
    return member
