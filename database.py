"""
database.py — работа с базой данных (SQLite) для бота учёта выгула собаки.

Хранит:
- walks — историю всех прогулок (кто, когда, заметка)
- chat_settings — профиль питомца и настройки чата (кличка, порода, возраст, интервал)

SQLite выбран потому что это один файл на диске, ничего дополнительно
устанавливать и настраивать не нужно — идеально для маленького личного бота.
"""

import sqlite3
from datetime import datetime
from contextlib import contextmanager

DB_PATH = "dog_walks.db"


@contextmanager
def get_connection():
    """Открывает соединение с БД и гарантированно закрывает его после использования."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # позволяет обращаться к колонкам по имени, row["name"]
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Создаёт таблицы, если их ещё нет. Вызывается один раз при старте бота.
    Также аккуратно добавляет новые колонки в уже существующую базу (миграция),
    чтобы не потерять данные тех, кто запускал бота ещё до появления профиля питомца."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS walks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                note TEXT,
                together INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                interval_hours REAL NOT NULL DEFAULT 8,
                pet_name TEXT NOT NULL DEFAULT 'собака'
            )
        """)

        # Миграция: добавляем колонки породы и возраста, если их ещё нет
        # (например, база была создана более ранней версией бота).
        for column, coltype in [("breed", "TEXT"), ("age_years", "REAL")]:
            try:
                conn.execute(f"ALTER TABLE chat_settings ADD COLUMN {column} {coltype}")
            except sqlite3.OperationalError:
                pass  # колонка уже существует — всё в порядке

        # Миграция: отметка "выгуляли вместе" для уже существующих баз.
        try:
            conn.execute("ALTER TABLE walks ADD COLUMN together INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # колонка уже существует — всё в порядке

        # Миграция: геолокация чата для погодных предупреждений.
        for column, coltype in [("city", "TEXT"), ("latitude", "REAL"), ("longitude", "REAL")]:
            try:
                conn.execute(f"ALTER TABLE chat_settings ADD COLUMN {column} {coltype}")
            except sqlite3.OperationalError:
                pass  # колонка уже существует — всё в порядке


def get_or_create_settings(chat_id: int) -> sqlite3.Row:
    """Возвращает настройки чата, создавая запись по умолчанию если её ещё нет."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO chat_settings (chat_id, interval_hours, pet_name) VALUES (?, 8, 'собака')",
                (chat_id,),
            )
            row = conn.execute(
                "SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return row


def get_all_chat_ids() -> list:
    """Все чаты, где бот когда-либо был запущен (использовалась команда /start)."""
    with get_connection() as conn:
        rows = conn.execute("SELECT chat_id FROM chat_settings").fetchall()
        return [row["chat_id"] for row in rows]


def set_pet_profile(chat_id: int, pet_name: str, breed: str, age_years: float, interval_hours: float):
    """Сохраняет полный профиль питомца — вызывается после диалога настройки в /start."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE chat_settings
               SET pet_name = ?, breed = ?, age_years = ?, interval_hours = ?
               WHERE chat_id = ?""",
            (pet_name, breed, age_years, interval_hours, chat_id),
        )


def set_interval(chat_id: int, hours: float):
    with get_connection() as conn:
        conn.execute(
            "UPDATE chat_settings SET interval_hours = ? WHERE chat_id = ?",
            (hours, chat_id),
        )


def set_pet_name(chat_id: int, name: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE chat_settings SET pet_name = ? WHERE chat_id = ?",
            (name, chat_id),
        )


def set_location(chat_id: int, city: str, latitude: float, longitude: float):
    """Сохраняет координаты чата — нужны для погодных предупреждений перед прогулкой."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE chat_settings SET city = ?, latitude = ?, longitude = ? WHERE chat_id = ?",
            (city, latitude, longitude, chat_id),
        )


def add_walk(chat_id: int, user_id: int, user_name: str, note: str = None, together: bool = False) -> int:
    """Записывает новую прогулку, возвращает её id (нужен чтобы потом прикрепить заметку).
    together=True — отметили, что гуляли вместе (кнопка "Выгуляли вместе")."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO walks (chat_id, user_id, user_name, timestamp, note, together) VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, user_id, user_name, datetime.now().isoformat(), note, int(together)),
        )
        return cur.lastrowid


def add_note_to_walk(walk_id: int, note: str):
    with get_connection() as conn:
        conn.execute("UPDATE walks SET note = ? WHERE id = ?", (note, walk_id))


def get_last_walk(chat_id: int):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM walks WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 1",
            (chat_id,),
        ).fetchone()


def get_history(chat_id: int, limit: int = 10):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM walks WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()


def get_stats(chat_id: int, since: datetime):
    """Список (user_name, cnt) за период с указанной даты, отсортированный по убыванию."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT user_name, COUNT(*) as cnt
            FROM walks
            WHERE chat_id = ? AND timestamp >= ?
            GROUP BY user_name
            ORDER BY cnt DESC
            """,
            (chat_id, since.isoformat()),
        ).fetchall()


def get_all_walks_for_export(chat_id: int):
    with get_connection() as conn:
        return conn.execute(
            "SELECT timestamp, user_name, note, together FROM walks WHERE chat_id = ? ORDER BY timestamp",
            (chat_id,),
        ).fetchall()
