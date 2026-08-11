"""
database.py — работа с базой данных (PostgreSQL) для Barbos.

Хранит:
- families — семья: кличка собаки, инвайт-код, режим напоминаний
- family_members — участники семьи (привязка tg_user_id к family_id)
- reminder_times — времена напоминаний для режима 'fixed'
- walks — история прогулок
- treatments — обработки (клещи, глистогонное, прививки, другое)

Строка подключения берётся из переменной окружения DATABASE_URL — на Railway
она уже есть в окружении при подключённом плагине Postgres; для локального
запуска положите её в .env (см. .env.example). Модуль используется как
единственная точка доступа к БД — и `bot.py`, и `api/*` всегда идут через
`db.*`, напрямую `psycopg2` не трогают.
"""

import os
import secrets
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Пороги наград за длительность прогулки (минуты) — см. ТЗ, раздел 5.
# 10 и 20 минут — нейтральные, в награды не попадают.
BRONZE_MINUTES = (30, 45)
SILVER_MINUTES = (60,)
GOLD_MINUTES = (90, 120)

PERIOD_INTERVALS = {"week": "7 days", "month": "30 days", "year": "365 days"}


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
    """Создаёт таблицы новой схемы. Вызывается один раз при старте бота/API.
    Старые таблицы (chat_id-схема) удаляются явно — старые тестовые данные
    сознательно не мигрируем (см. ТЗ, раздел 1/14), а без явного DROP
    `CREATE TABLE IF NOT EXISTS walks` молча оставил бы старую схему колонок.

    Важно: init_db() вызывается при каждом старте и bot-сервиса, и api-сервиса —
    дроп старой `walks` должен сработать РОВНО ОДИН РАЗ, при переезде со старой
    схемы. Иначе каждый рестарт стирал бы уже накопленную историю прогулок."""
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'walks'"
        )
        existing_walks_columns = {row["column_name"] for row in cur.fetchall()}
        is_old_schema = existing_walks_columns and "family_id" not in existing_walks_columns
        if is_old_schema:
            cur.execute("DROP TABLE IF EXISTS walks CASCADE")
        cur.execute("DROP TABLE IF EXISTS chat_settings CASCADE")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS families (
                id SERIAL PRIMARY KEY,
                pet_name TEXT NOT NULL,
                invite_code TEXT UNIQUE NOT NULL,
                reminder_mode TEXT NOT NULL DEFAULT 'fixed',
                interval_hours REAL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        # IANA-имя таймзоны (например 'Europe/Moscow') — нужно, чтобы 'fixed'-время
        # напоминаний планировалось по локальному времени семьи, а не по UTC.
        # Не было в исходной схеме ТЗ, поэтому добавляется отдельной колонкой,
        # как и breed/age_years в старой SQLite-версии этого проекта.
        cur.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'UTC'")
        # 'male' | 'female' — для согласования рода в текстах Mini App (например,
        # карточка настроения: "бодра/заждалась" для суки, "бодр/заждался" для кобеля).
        cur.execute("ALTER TABLE families ADD COLUMN IF NOT EXISTS pet_sex TEXT NOT NULL DEFAULT 'female'")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS family_members (
                id SERIAL PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
                tg_user_id BIGINT NOT NULL,
                display_name TEXT NOT NULL,
                tg_chat_id BIGINT,
                joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (family_id, tg_user_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reminder_times (
                id SERIAL PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
                time_of_day TIME NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS walks (
                id SERIAL PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
                tg_user_id BIGINT NOT NULL,
                walked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                duration_minutes INTEGER,
                note TEXT,
                together BOOLEAN NOT NULL DEFAULT false
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS treatments (
                id SERIAL PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                custom_name TEXT,
                treated_on DATE NOT NULL,
                drug_name TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)


# ---------- Families / members ----------

def _generate_invite_code() -> str:
    """Короткий URL-safe код для инвайт-ссылки. Энтропии (~13 символов base64url)
    достаточно, чтобы не думать о коллизиях — отдельный retry-цикл не нужен."""
    return secrets.token_urlsafe(9)


def create_family(
    pet_name: str,
    reminder_mode: str,
    interval_hours: float,
    times: list,
    tg_user_id: int,
    display_name: str,
    timezone: str = "UTC",
    pet_sex: str = "female",
) -> dict:
    """Создаёт семью, времена напоминаний (для 'fixed') и первого участника — одной транзакцией.
    Возвращает {family_id, invite_code}. tg_chat_id участника = tg_user_id: Mini App открывается
    из личного чата с ботом, а для приватных чатов в Telegram chat_id всегда совпадает с user_id —
    другого способа узнать личный chat_id у initData нет.

    timezone — IANA-имя (например 'Europe/Moscow'), определяется на фронте через
    Intl.DateTimeFormat().resolvedOptions().timeZone и используется ботом, чтобы
    планировать 'fixed'-напоминания по локальному времени семьи, а не по UTC."""
    invite_code = _generate_invite_code()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO families (pet_name, invite_code, reminder_mode, interval_hours, timezone, pet_sex)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, invite_code""",
            (pet_name, invite_code, reminder_mode, interval_hours, timezone, pet_sex),
        )
        family = cur.fetchone()
        family_id = family["id"]

        if reminder_mode == "fixed":
            for t in times:
                cur.execute(
                    "INSERT INTO reminder_times (family_id, time_of_day) VALUES (%s, %s)",
                    (family_id, t),
                )

        cur.execute(
            """INSERT INTO family_members (family_id, tg_user_id, display_name, tg_chat_id)
               VALUES (%s, %s, %s, %s)""",
            (family_id, tg_user_id, display_name, tg_user_id),
        )

        return {"family_id": family_id, "invite_code": family["invite_code"]}


def get_family(family_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM families WHERE id = %s", (family_id,))
        return cur.fetchone()


def get_family_by_invite_code(invite_code: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM families WHERE invite_code = %s", (invite_code,))
        return cur.fetchone()


def get_all_families():
    """Все семьи — используется ботом для сверки расписания напоминаний."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM families")
        return cur.fetchall()


def update_family_profile(family_id: int, fields: dict):
    """fields — словарь только тех колонок, которые нужно поменять (pet_name/pet_sex).
    Используется настройками профиля — правки после онбординга."""
    if not fields:
        return
    columns = list(fields.keys())
    set_clause = ", ".join(f"{col} = %s" for col in columns)
    values = [fields[col] for col in columns]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE families SET {set_clause} WHERE id = %s", (*values, family_id))


def set_reminder_config(family_id: int, reminder_mode: str, interval_hours: float, times: list):
    """Обновляет режим напоминаний семьи и (для 'fixed') полностью пересобирает reminder_times."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE families SET reminder_mode = %s, interval_hours = %s WHERE id = %s",
            (reminder_mode, interval_hours, family_id),
        )
        cur.execute("DELETE FROM reminder_times WHERE family_id = %s", (family_id,))
        if reminder_mode == "fixed":
            for t in times:
                cur.execute(
                    "INSERT INTO reminder_times (family_id, time_of_day) VALUES (%s, %s)",
                    (family_id, t),
                )


def get_reminder_times(family_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT time_of_day FROM reminder_times WHERE family_id = %s ORDER BY time_of_day",
            (family_id,),
        )
        return [row["time_of_day"] for row in cur.fetchall()]


def join_family(family_id: int, tg_user_id: int, display_name: str) -> dict:
    """Подключает участника к существующей семье (по инвайт-коду). Идемпотентно —
    повторный заход того же tg_user_id обновляет имя, а не падает на UNIQUE."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO family_members (family_id, tg_user_id, display_name, tg_chat_id)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (family_id, tg_user_id)
               DO UPDATE SET display_name = EXCLUDED.display_name""",
            (family_id, tg_user_id, display_name, tg_user_id),
        )
        return {"family_id": family_id}


def get_family_members(family_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM family_members WHERE family_id = %s ORDER BY joined_at",
            (family_id,),
        )
        return cur.fetchall()


def get_member_by_tg_user_id(tg_user_id: int):
    """Ищет членство пользователя — так аутентификация в API узнаёт его family_id.
    Считаем, что человек состоит максимум в одной семье (модель — «домохозяйство из 1-2 человек»)."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM family_members WHERE tg_user_id = %s LIMIT 1", (tg_user_id,))
        return cur.fetchone()


# ---------- Walks ----------

def add_walk(family_id: int, tg_user_id: int, duration_minutes: int = None, note: str = None, together: bool = False) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO walks (family_id, tg_user_id, duration_minutes, note, together)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (family_id, tg_user_id, duration_minutes, note, together),
        )
        return cur.fetchone()["id"]


def update_walk(walk_id: int, family_id: int, fields: dict):
    """fields — словарь только тех колонок, которые нужно поменять (duration_minutes/note/together)."""
    if not fields:
        return
    columns = list(fields.keys())
    set_clause = ", ".join(f"{col} = %s" for col in columns)
    values = [fields[col] for col in columns]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE walks SET {set_clause} WHERE id = %s AND family_id = %s",
            (*values, walk_id, family_id),
        )


def get_walk(walk_id: int, family_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM walks WHERE id = %s AND family_id = %s", (walk_id, family_id))
        return cur.fetchone()


def get_walks(family_id: int, days: int = None, limit: int = None, offset: int = 0):
    query = "SELECT * FROM walks WHERE family_id = %s"
    params = [family_id]
    if days is not None:
        query += " AND walked_at >= now() - make_interval(days => %s)"
        params.append(days)
    query += " ORDER BY walked_at DESC"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()


def get_last_walk(family_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM walks WHERE family_id = %s ORDER BY walked_at DESC LIMIT 1",
            (family_id,),
        )
        return cur.fetchone()


# ---------- Treatments ----------

def add_treatment(family_id: int, category: str, treated_on, custom_name: str = None, drug_name: str = None) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO treatments (family_id, category, custom_name, treated_on, drug_name)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (family_id, category, custom_name, treated_on, drug_name),
        )
        return cur.fetchone()["id"]


def update_treatment(treatment_id: int, family_id: int, fields: dict):
    if not fields:
        return
    columns = list(fields.keys())
    set_clause = ", ".join(f"{col} = %s" for col in columns)
    values = [fields[col] for col in columns]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE treatments SET {set_clause} WHERE id = %s AND family_id = %s",
            (*values, treatment_id, family_id),
        )


def get_treatment(treatment_id: int, family_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM treatments WHERE id = %s AND family_id = %s",
            (treatment_id, family_id),
        )
        return cur.fetchone()


def get_treatment_categories(family_id: int):
    """Последняя запись по каждой связке (category, custom_name) — для карточек экрана
    «Медицина». Для фиксированных категорий custom_name всегда NULL, для 'other' —
    отдельная карточка на каждое введённое пользователем название."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT DISTINCT ON (category, custom_name)
                      category, custom_name, treated_on, drug_name
               FROM treatments
               WHERE family_id = %s
               ORDER BY category, custom_name, treated_on DESC""",
            (family_id,),
        )
        return cur.fetchall()


def get_treatment_history(family_id: int, category: str, custom_name: str = None):
    query = "SELECT * FROM treatments WHERE family_id = %s AND category = %s"
    params = [family_id, category]
    if custom_name is not None:
        query += " AND custom_name = %s"
        params.append(custom_name)
    else:
        query += " AND custom_name IS NULL"
    query += " ORDER BY treated_on DESC"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()


def get_all_treatments(family_id: int):
    """Вся история обработок семьи, вне зависимости от категории — для CSV-экспорта."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM treatments WHERE family_id = %s ORDER BY treated_on DESC",
            (family_id,),
        )
        return cur.fetchall()


# ---------- Статистика ----------

def get_stats(family_id: int, period: str) -> dict:
    """Агрегаты для экрана «Статистика». period — 'week' | 'month' | 'year'.

    Логика подсчёта (см. ТЗ, раздел 9):
    - total — каждая прогулка считается ровно один раз, вне зависимости от together
    - by_member/rewards — прогулка с together=true засчитывается ОБОИМ участникам полностью,
      поэтому сумма личных показателей может превышать total (ожидаемое поведение)
    - в rewards попадают только прогулки с указанной длительностью
    """
    interval = PERIOD_INTERVALS[period]
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            f"SELECT COUNT(*) AS total FROM walks WHERE family_id = %s AND walked_at >= now() - interval '{interval}'",
            (family_id,),
        )
        total = cur.fetchone()["total"]

        cur.execute(
            f"""SELECT fm.id AS member_id, fm.display_name,
                       COUNT(*) FILTER (WHERE w.tg_user_id = fm.tg_user_id OR w.together) AS walk_count
                FROM family_members fm
                LEFT JOIN walks w
                       ON w.family_id = fm.family_id AND w.walked_at >= now() - interval '{interval}'
                WHERE fm.family_id = %s
                GROUP BY fm.id, fm.display_name
                ORDER BY walk_count DESC""",
            (family_id,),
        )
        by_member = cur.fetchall()

        cur.execute(
            f"""SELECT fm.id AS member_id, fm.display_name,
                       COUNT(*) FILTER (
                           WHERE (w.tg_user_id = fm.tg_user_id OR w.together)
                             AND w.duration_minutes = ANY(%(bronze)s)
                       ) AS bronze,
                       COUNT(*) FILTER (
                           WHERE (w.tg_user_id = fm.tg_user_id OR w.together)
                             AND w.duration_minutes = ANY(%(silver)s)
                       ) AS silver,
                       COUNT(*) FILTER (
                           WHERE (w.tg_user_id = fm.tg_user_id OR w.together)
                             AND w.duration_minutes = ANY(%(gold)s)
                       ) AS gold
                FROM family_members fm
                LEFT JOIN walks w
                       ON w.family_id = fm.family_id AND w.walked_at >= now() - interval '{interval}'
                WHERE fm.family_id = %(family_id)s
                GROUP BY fm.id, fm.display_name""",
            {
                "bronze": list(BRONZE_MINUTES),
                "silver": list(SILVER_MINUTES),
                "gold": list(GOLD_MINUTES),
                "family_id": family_id,
            },
        )
        rewards = cur.fetchall()

        return {"total": total, "by_member": by_member, "rewards": rewards}
