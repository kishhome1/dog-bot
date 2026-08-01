"""
bot.py — Telegram-бот для учёта выгула собаки.

Что умеет:
- при первом /start проводит короткий диалог: кличка, порода, возраст,
  когда следующий выгул — и сам подбирает разумный интервал напоминаний
- присылает напоминание о прогулке; отсчёт идёт от последней ЗАПИСАННОЙ
  прогулки, а не по жёсткому расписанию — выгуляли раньше срока,
  следующее напоминание сдвинется соответственно
- если через час после напоминания никто не отметился — присылает повторный пинг
- кнопкой отмечается кто выгулял (по имени в Telegram), можно добавить заметку
- /stats — статистика за сегодня и неделю
- /history — последние прогулки
- /export — выгрузка всей истории в CSV файл
- /setinterval, /setpet — точечная настройка без повторного диалога

Запуск: python bot.py
Требует переменную окружения BOT_TOKEN (см. .env.example и README.md)
"""

import logging
import csv
import io
import re
import os
from collections import defaultdict
from datetime import datetime, timedelta

import httpx
import matplotlib
matplotlib.use("Agg")  # без GUI — бот рендерит графики на сервере без дисплея
import matplotlib.pyplot as plt

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import database as db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# chat_id -> (message_id запроса "пришлите заметку", walk_id к которому она относится)
pending_note_prompts: dict = {}

# Состояния диалога настройки профиля питомца (используется в /start)
ASK_NAME, ASK_BREED, ASK_AGE, ASK_NEXT_WALK = range(4)

# Породы, которым обычно нужны более частые прогулки из-за маленького размера
SMALL_BREED_KEYWORDS = [
    "чихуахуа", "той-терьер", "той терьер", "йорк", "шпиц", "такса",
    "мопс", "папильон", "болонка", "карликов", "мини",
    "chihuahua", "yorkshire", "pomeranian", "dachshund", "pug",
]

# Коды погоды Open-Meteo (стандарт WMO), которые означают дождь или грозу.
# https://open-meteo.com/en/docs — таблица WMO Weather interpretation codes
RAIN_WEATHER_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}

WEEKDAY_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


# ---------- Вспомогательные функции ----------

def user_display_name(user) -> str:
    return user.first_name or user.username or "Кто-то"


def format_walk_time(iso_ts: str) -> str:
    return datetime.fromisoformat(iso_ts).strftime("%d.%m %H:%M")


def compute_interval(age_years: float, breed: str) -> float:
    """Простая эвристика подбора интервала между прогулками по возрасту и породе.
    Это разумный стартовый ориентир, а не ветеринарная рекомендация — в любой
    момент можно поправить вручную через /setinterval."""
    if age_years < 0.5:
        base = 3.0   # щенки до полугода — часто и понемногу
    elif age_years < 1:
        base = 5.0   # молодая собака, ещё не полностью развит контроль
    elif age_years >= 8:
        base = 6.0   # пожилая собака — обычно чаще, но короче
    else:
        base = 8.0   # взрослая собака — стандартный интервал

    breed_lower = breed.lower()
    if any(keyword in breed_lower for keyword in SMALL_BREED_KEYWORDS):
        base = max(base - 1.0, 3.0)  # маленькие породы — чуть чаще

    return base


def parse_next_walk_input(text: str):
    """Понимает время в формате ЧЧ:ММ (например '19:30') либо просто число часов
    (например '3'). Возвращает задержку в секундах или None если не смог разобрать."""
    text = text.strip().replace(",", ".")

    match = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    try:
        hours = float(text)
        if 0 < hours <= 48:
            return hours * 3600
    except ValueError:
        pass

    return None


async def geocode_city(city_name: str):
    """Ищет город через геокодер Open-Meteo (бесплатный, без ключа).
    Возвращает (широта, долгота, найденное название) либо None если не нашёл."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city_name, "count": 1, "language": "ru", "format": "json"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.warning("Не удалось найти город '%s': %s", city_name, e)
        return None

    results = data.get("results")
    if not results:
        return None

    result = results[0]
    return result["latitude"], result["longitude"], result.get("name", city_name)


async def get_rain_warning(latitude: float, longitude: float):
    """Смотрит почасовой прогноз Open-Meteo на ближайшие 3 часа для заданных координат.
    Если ожидается дождь/гроза (по коду погоды WMO или высокой вероятности осадков) —
    возвращает текст предупреждения, иначе None. Молчит при сбое запроса — погода
    не должна ломать основной сценарий напоминания."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "hourly": "precipitation_probability,weathercode",
                    "forecast_days": 1,
                    "timezone": "auto",
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.warning("Не удалось получить прогноз погоды: %s", e)
        return None

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    probabilities = hourly.get("precipitation_probability", [])
    codes = hourly.get("weathercode", [])

    now = datetime.now()
    for i, t in enumerate(times):
        forecast_time = datetime.fromisoformat(t)
        if forecast_time < now - timedelta(minutes=30):
            continue
        if forecast_time > now + timedelta(hours=3):
            break

        code = codes[i] if i < len(codes) else None
        probability = probabilities[i] if i < len(probabilities) else 0
        if code in RAIN_WEATHER_CODES or probability >= 60:
            return "☔ Ожидается дождь — возьмите зонт/дождевик для собаки!"

    return None


def reschedule_reminder(context: ContextTypes.DEFAULT_TYPE, chat_id: int, delay_seconds: float):
    """Убирает старые запланированные напоминания для чата и ставит новое через delay_seconds."""
    for job in context.job_queue.get_jobs_by_name(f"reminder_{chat_id}"):
        job.schedule_removal()
    for job in context.job_queue.get_jobs_by_name(f"nudge_{chat_id}"):
        job.schedule_removal()

    context.job_queue.run_once(
        send_reminder,
        when=timedelta(seconds=delay_seconds),
        chat_id=chat_id,
        name=f"reminder_{chat_id}",
    )


async def schedule_next_reminder(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Ставит следующее напоминание через interval_hours от текущего момента.
    Используется после того как кто-то отметил прогулку кнопкой."""
    settings = db.get_or_create_settings(chat_id)
    reschedule_reminder(context, chat_id, settings["interval_hours"] * 3600)


# ---------- Диалог настройки профиля питомца (/start) ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db.get_or_create_settings(chat_id)
    context.chat_data["setup"] = {}

    await update.message.reply_text(
        "🐕 Привет! Давай быстро настроим бота под твою собаку — это займёт 4 вопроса.\n\n"
        "Как зовут питомца?"
    )
    return ASK_NAME


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["setup"]["name"] = update.message.text.strip()
    await update.message.reply_text("Какая порода? (можно примерно, или просто «дворняга»)")
    return ASK_BREED


async def ask_breed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["setup"]["breed"] = update.message.text.strip()
    await update.message.reply_text(
        "Сколько лет питомцу? Можно дробно, например 0.5 — для полугода."
    )
    return ASK_AGE


async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        age = float(text)
        if not (0 <= age <= 30):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Не понял возраст. Введите число, например: 2 или 0.5"
        )
        return ASK_AGE

    context.chat_data["setup"]["age"] = age
    await update.message.reply_text(
        "Когда планируется следующий выгул?\n\n"
        "Напиши время в формате ЧЧ:ММ (например 19:30) "
        "или просто через сколько часов, например 3"
    )
    return ASK_NEXT_WALK


async def ask_next_walk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    delay_seconds = parse_next_walk_input(update.message.text)
    if delay_seconds is None:
        await update.message.reply_text(
            "Не понял формат. Напиши время как 19:30, либо количество часов, например 3"
        )
        return ASK_NEXT_WALK

    setup = context.chat_data["setup"]
    chat_id = update.effective_chat.id
    interval = compute_interval(setup["age"], setup["breed"])

    db.set_pet_profile(chat_id, setup["name"], setup["breed"], setup["age"], interval)
    reschedule_reminder(context, chat_id, delay_seconds)

    await update.message.reply_text(
        f"Готово! 🐾\n\n"
        f"Питомец: {setup['name']} ({setup['breed']}, {setup['age']} лет)\n"
        f"Интервал между напоминаниями подобрал: {interval:g} ч. "
        f"— это стартовый ориентир по возрасту и породе, а не ветеринарная норма.\n"
        f"Изменить в любой момент: /setinterval <часы>\n\n"
        f"Команды:\n"
        f"/stats — график активности по дням недели\n"
        f"/history — последние прогулки\n"
        f"/export — история в CSV\n"
        f"/setpet <имя> — быстро сменить кличку\n"
        f"/setlocation <город> — включить предупреждение о дожде перед прогулкой\n"
        f"/start — пройти настройку заново\n\n"
        f"Первое напоминание придёт в указанное время!"
    )
    return ConversationHandler.END


async def cancel_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data.pop("setup", None)
    await update.message.reply_text("Настройка отменена. Наберите /start когда будете готовы.")
    return ConversationHandler.END


# ---------- Напоминания ----------

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    settings = db.get_or_create_settings(chat_id)
    pet = settings["pet_name"]

    text = f"🐾 Время выгулять {pet}!"
    if settings["latitude"] is not None and settings["longitude"] is not None:
        warning = await get_rain_warning(settings["latitude"], settings["longitude"])
        if warning:
            text += f"\n\n{warning}"

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"✅ Я выгулял(а) {pet}", callback_data="walked")],
            [InlineKeyboardButton("👥 Выгуляли вместе", callback_data="walked_together")],
        ]
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
    )

    # Если через час никто не отметился — мягкий повторный пинг.
    context.job_queue.run_once(
        send_nudge,
        when=timedelta(hours=1),
        chat_id=chat_id,
        name=f"nudge_{chat_id}",
    )


async def send_nudge(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    last_walk = db.get_last_walk(chat_id)

    if last_walk:
        last_ts = datetime.fromisoformat(last_walk["timestamp"])
        if datetime.now() - last_ts < timedelta(hours=1, minutes=5):
            return

    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ Прошёл час, а прогулки так и не было — не забудьте!",
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нажатие кнопки 'Я выгулял(а)' или 'Выгуляли вместе'."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    user = query.from_user
    name = user_display_name(user)
    together = query.data == "walked_together"

    walk_id = db.add_walk(chat_id, user.id, name, together=together)
    now_str = datetime.now().strftime("%H:%M")

    if together:
        text = f"✅ Выгуляли вместе (отметил(а) {name}) в {now_str}. Записал!"
    else:
        text = f"✅ {name} выгулял(а) в {now_str}. Записал!"

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📝 Добавить заметку", callback_data=f"note_{walk_id}")]]
    )
    await query.edit_message_text(
        text=text,
        reply_markup=keyboard,
    )

    await schedule_next_reminder(context, chat_id)


async def note_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нажатие кнопки 'Добавить заметку' — просим прислать текст ответом на сообщение."""
    query = update.callback_query
    await query.answer()

    walk_id = int(query.data.split("_")[1])
    chat_id = query.message.chat_id

    prompt = await context.bot.send_message(
        chat_id=chat_id,
        text="✍️ Ответьте на ЭТО сообщение текстом заметки "
             "(например: «нашли клеща», «мало ел», «хромал на лапу»).",
    )
    pending_note_prompts[chat_id] = (prompt.message_id, walk_id)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ловит ответ на запрос заметки. Работает через reply — поэтому не нужно
    отключать privacy mode бота в групповом чате."""
    chat_id = update.effective_chat.id
    message = update.message

    if chat_id not in pending_note_prompts:
        return

    prompt_id, walk_id = pending_note_prompts[chat_id]

    if not message.reply_to_message or message.reply_to_message.message_id != prompt_id:
        return

    db.add_note_to_walk(walk_id, message.text)
    del pending_note_prompts[chat_id]
    await message.reply_text("📝 Заметка сохранена!")


# ---------- Статистика и история ----------

def build_weekday_activity_chart(walks) -> io.BytesIO:
    """Строит столбчатую диаграмму: сколько раз каждый гулял в каждый день недели.
    walks — строки (timestamp, user_name) из db.get_walks_by_weekday()."""
    counts = defaultdict(lambda: [0] * 7)
    for w in walks:
        weekday = datetime.fromisoformat(w["timestamp"]).weekday()  # 0=Пн ... 6=Вс
        counts[w["user_name"]][weekday] += 1

    users = sorted(counts.keys())
    x = list(range(7))
    bar_width = 0.8 / len(users)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for i, user in enumerate(users):
        offset = (i - (len(users) - 1) / 2) * bar_width
        positions = [xi + offset for xi in x]
        ax.bar(positions, counts[user], bar_width, label=user)

    ax.set_xticks(x)
    ax.set_xticklabels(WEEKDAY_LABELS)
    ax.set_ylabel("Прогулок")
    ax.set_title("Активность по дням недели")
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150)
    plt.close(fig)
    buffer.seek(0)
    return buffer


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    walks = db.get_walks_by_weekday(chat_id)

    if not walks:
        await update.message.reply_text("Пока нет данных для статистики — ни одной прогулки не записано.")
        return

    chart = build_weekday_activity_chart(walks)

    caption = "📊 Активность по дням недели"
    last_walk = db.get_last_walk(chat_id)
    if last_walk:
        caption += (
            f"\n🕐 Последняя прогулка: {format_walk_time(last_walk['timestamp'])} "
            f"({last_walk['user_name']})"
        )

    await update.message.reply_photo(photo=chart, caption=caption)


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    walks = db.get_history(chat_id, limit=10)

    if not walks:
        await update.message.reply_text("История пока пустая.")
        return

    lines = ["📖 Последние прогулки:", ""]
    for w in walks:
        line = f"• {format_walk_time(w['timestamp'])} — {w['user_name']}"
        if w["together"]:
            line += " 👥 (вместе)"
        if w["note"]:
            line += f"\n   💬 {w['note']}"
        lines.append(line)

    await update.message.reply_text("\n".join(lines))


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    walks = db.get_all_walks_for_export(chat_id)

    if not walks:
        await update.message.reply_text("Пока нечего экспортировать.")
        return

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Дата и время", "Кто выгуливал", "Вместе", "Заметка"])
    for w in walks:
        writer.writerow([
            format_walk_time(w["timestamp"]),
            w["user_name"],
            "Да" if w["together"] else "",
            w["note"] or "",
        ])

    byte_buffer = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))
    await update.message.reply_document(
        document=byte_buffer,
        filename="dog_walks_history.csv",
    )


# ---------- Точечные настройки (без полного диалога) ----------

async def setinterval_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Укажите интервал в часах, например: /setinterval 8")
        return
    try:
        hours = float(context.args[0])
        if hours <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Нужно положительное число, например: /setinterval 8")
        return

    db.set_interval(chat_id, hours)
    await update.message.reply_text(f"⏱ Интервал напоминаний установлен: {hours} ч.")
    await schedule_next_reminder(context, chat_id)


async def setpet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Укажите имя, например: /setpet Рекс")
        return
    name = " ".join(context.args)
    db.set_pet_name(chat_id, name)
    await update.message.reply_text(f"🐕 Теперь питомца зовут {name}!")


async def setlocation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            "Укажите город, например: /setlocation Москва\n\n"
            "Это нужно, чтобы бот мог предупреждать о дожде перед прогулкой."
        )
        return

    city_name = " ".join(context.args)
    result = await geocode_city(city_name)
    if result is None:
        await update.message.reply_text(
            f"Не нашёл город «{city_name}». Попробуйте написать иначе, например на английском."
        )
        return

    latitude, longitude, resolved_name = result
    db.set_location(chat_id, resolved_name, latitude, longitude)
    await update.message.reply_text(
        f"📍 Место сохранено: {resolved_name}\n"
        f"Теперь буду проверять прогноз дождя перед напоминанием о прогулке ☔"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "/start — пройти (или перепройти) настройку профиля питомца\n"
        "/stats — график активности по дням недели\n"
        "/history — последние 10 прогулок\n"
        "/setinterval <часы> — изменить интервал напоминаний вручную\n"
        "/setpet <имя> — быстро сменить кличку\n"
        "/setlocation <город> — включить предупреждение о дожде перед прогулкой\n"
        "/export — выгрузить историю в CSV"
    )
    await update.message.reply_text(text)


# ---------- Восстановление напоминаний после перезапуска ----------

async def post_init(application: Application):
    """При старте бота (в том числе после перезапуска хостингом) восстанавливаем
    напоминания для всех чатов, которые уже пользовались ботом."""
    chat_ids = db.get_all_chat_ids()
    for chat_id in chat_ids:
        settings = db.get_or_create_settings(chat_id)
        interval = settings["interval_hours"]
        last_walk = db.get_last_walk(chat_id)

        if last_walk:
            last_ts = datetime.fromisoformat(last_walk["timestamp"])
            delay = (last_ts + timedelta(hours=interval) - datetime.now()).total_seconds()
            delay = max(delay, 5)
        else:
            delay = interval * 3600

        application.job_queue.run_once(
            send_reminder,
            when=timedelta(seconds=delay),
            chat_id=chat_id,
            name=f"reminder_{chat_id}",
        )

    if chat_ids:
        logger.info("Восстановлены напоминания для %d чатов", len(chat_ids))


# ---------- Запуск ----------

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не найден BOT_TOKEN. Скопируйте .env.example в .env и вставьте туда токен от @BotFather."
        )

    db.init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    setup_conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_BREED: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_breed)],
            ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
            ASK_NEXT_WALK: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_next_walk)],
        },
        fallbacks=[CommandHandler("cancel", cancel_setup)],
    )

    app.add_handler(setup_conversation)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("setinterval", setinterval_command))
    app.add_handler(CommandHandler("setpet", setpet_command))
    app.add_handler(CommandHandler("setlocation", setlocation_command))

    app.add_handler(CallbackQueryHandler(button_callback, pattern="^walked(_together)?$"))
    app.add_handler(CallbackQueryHandler(note_button_callback, pattern="^note_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Бот запущен, жду сообщений...")
    app.run_polling()


if __name__ == "__main__":
    main()
