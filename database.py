"""
database.py — работа с базой данных (PostgreSQL) для бота учёта выгула собаки.

Хранит:
- walks — историю всех прогулок (кто, когда, заметка)
- chat_settings — профиль питомца и настройки чата (кличка, порода, возраст, интервал)

Строка подключения берётся из переменной окружения DATABASE_URL — на Railway
она уже есть в окружении при подключённом плагине Postgres; для локального
запуска положите её в .env (см. .env.example).
"""

import os
from datetime import datetime
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


@contextmanager
def get_connection():
    """Открывает соединение с БД и гарантированно закрывает его после использования."""
    if not DATABASE_URL:
        raise RuntimeError(
            "Не найден DATABASE_URL. На Railway он появляется автоматически при "
            "подключённом плагине Postgres; локально добавьте его в .env."
        )
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Создаёт таблицы, если их ещё нет. Вызывается один раз при старте бота.
    Новые колонки добавляются через ADD COLUMN IF NOT EXISTS — Postgres
    поддерживает это нативно, отдельная миграционная обвязка не нужна."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS walks (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                user_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                note TEXT,
                together INTEGER NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id BIGINT PRIMARY KEY,
                interval_hours REAL NOT NULL DEFAULT 8,
                pet_name TEXT NOT NULL DEFAULT 'собака'
            )
        """)

        # chat_id/user_id — BIGINT: у Telegram встречаются id за пределами диапазона INTEGER.
        cur.execute("ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS breed TEXT")
        cur.execute("ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS age_years REAL")
        cur.execute("ALTER TABLE walks ADD COLUMN IF NOT EXISTS together INTEGER NOT NULL DEFAULT 0")


def get_or_create_settings(chat_id: int):
    """Возвращает настройки чата, создавая запись по умолчанию если её ещё нет."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM chat_settings WHERE chat_id = %s", (chat_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO chat_settings (chat_id, interval_hours, pet_name) VALUES (%s, 8, 'собака')",
                (chat_id,),
            )
            cur.execute("SELECT * FROM chat_settings WHERE chat_id = %s", (chat_id,))
            row = cur.fetchone()
        return row


def get_all_chat_ids() -> list:
    """Все чаты, где бот когда-либо был запущен (использовалась команда /start)."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT chat_id FROM chat_settings")
        return [row["chat_id"] for row in cur.fetchall()]


def set_pet_profile(chat_id: int, pet_name: str, breed: str, age_years: float, interval_hours: float):
    """Сохраняет полный профиль питомца — вызывается после диалога настройки в /start."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE chat_settings
               SET pet_name = %s, breed = %s, age_years = %s, interval_hours = %s
               WHERE chat_id = %s""",
            (pet_name, breed, age_years, interval_hours, chat_id),
        )


def set_interval(chat_id: int, hours: float):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE chat_settings SET interval_hours = %s WHERE chat_id = %s",
            (hours, chat_id),
        )


def set_pet_name(chat_id: int, name: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE chat_settings SET pet_name = %s WHERE chat_id = %s",
            (name, chat_id),
        )


def add_walk(chat_id: int, user_id: int, user_name: str, note: str = None, together: bool = False) -> int:
    """Записывает новую прогулку, возвращает её id (нужен чтобы потом прикрепить заметку).
    together=True — отметили, что гуляли вместе (кнопка "Выгуляли вместе")."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO walks (chat_id, user_id, user_name, timestamp, note, together)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (chat_id, user_id, user_name, datetime.now().isoformat(), note, int(together)),
        )
        return cur.fetchone()["id"]


def add_note_to_walk(walk_id: int, note: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE walks SET note = %s WHERE id = %s", (note, walk_id))


def get_last_walk(chat_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM walks WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1",
            (chat_id,),
        )
        return cur.fetchone()


def get_history(chat_id: int, limit: int = 10):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM walks WHERE chat_id = %s ORDER BY timestamp DESC LIMIT %s",
            (chat_id, limit),
        )
        return cur.fetchall()


def get_walks_by_weekday(chat_id: int):
    """Возвращает (timestamp, user_name) по всем прогулкам чата — используется
    для построения графика активности по дням недели в /stats."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT timestamp, user_name FROM walks WHERE chat_id = %s ORDER BY timestamp",
            (chat_id,),
        )
        return cur.fetchall()


def get_all_walks_for_export(chat_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT timestamp, user_name, note, together FROM walks WHERE chat_id = %s ORDER BY timestamp",
            (chat_id,),
        )
        return cur.fetchall()
