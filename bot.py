"""
bot.py — точка входа Barbos в Telegram и канал push-напоминаний.

Весь UI (онбординг, отметка прогулок, медицина, статистика) живёт в Mini App
поверх FastAPI (см. api/). Бот отвечает только за:
- /start — одно сообщение с кнопкой «Открыть Barbos» (WebApp), включая передачу
  инвайт-кода из deep link'а (`/start invite_<code>`) дальше в Mini App
- рассылку напоминаний в личку каждому участнику семьи (chat_id участника
  в приватном чате с ботом совпадает с его tg_user_id — Mini App открывается
  именно из этого чата)

Расписание напоминаний хранится не в памяти процесса, а пересобирается из
Postgres каждые несколько минут через reconcile_reminders() — это и есть
восстановление после рестарта, и реакция на прогулки/изменения настроек,
которые пишет отдельный api-сервис.

Запуск: python bot.py
Требует BOT_TOKEN и MINIAPP_URL (см. .env.example и README.md)
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

import database as db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MINIAPP_URL = os.getenv("MINIAPP_URL")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

RECONCILE_INTERVAL = timedelta(minutes=5)
DEFAULT_INTERVAL_HOURS = 8


# ---------- /start ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = MINIAPP_URL
    if context.args and context.args[0].startswith("invite_"):
        invite_code = context.args[0][len("invite_"):]
        url = f"{MINIAPP_URL}?invite={invite_code}"

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🐕 Открыть Barbos", web_app=WebAppInfo(url=url))]]
    )
    await update.message.reply_text(
        "Привет! Открой Barbos, чтобы настроить напоминания и отмечать прогулки.",
        reply_markup=keyboard,
    )


# ---------- Отправка напоминаний ----------

async def send_to_family(context: ContextTypes.DEFAULT_TYPE, family_id: int, text: str):
    """Шлёт сообщение в личку каждому участнику семьи. Участник без известного
    tg_chat_id (гипотетически — если запись когда-то создали в обход онбординга)
    молча пропускается; сбой отправки одному не должен прерывать рассылку остальным."""
    family = db.get_family(family_id)
    if family is None:
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🐕 Открыть Barbos", web_app=WebAppInfo(url=MINIAPP_URL))]]
    )
    for member in db.get_family_members(family_id):
        if not member["tg_chat_id"]:
            continue
        try:
            await context.bot.send_message(chat_id=member["tg_chat_id"], text=text, reply_markup=keyboard)
        except TelegramError as e:
            logger.warning(
                "Не удалось отправить напоминание family_id=%s tg_chat_id=%s: %s",
                family_id, member["tg_chat_id"], e,
            )


def schedule_once(context: ContextTypes.DEFAULT_TYPE, callback, delay_seconds: float, name: str, data):
    """run_once с предварительной отменой существующего job'а того же имени —
    так же, как reschedule_reminder делал это в старой версии бота."""
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    context.job_queue.run_once(callback, when=timedelta(seconds=max(delay_seconds, 1)), data=data, name=name)


async def send_nudge(context: ContextTypes.DEFAULT_TYPE):
    """Мягкий повторный пинг через час после напоминания — общий для обоих режимов.
    Молчит, если прогулку уже отметили: так же выполняется требование ТЗ «отменить
    оставшееся напоминание слота после отметки», без явной межпроцессной отмены."""
    family_id = context.job.data
    last_walk = db.get_last_walk(family_id)
    if last_walk and datetime.now(timezone.utc) - last_walk["walked_at"] < timedelta(hours=1, minutes=5):
        return
    await send_to_family(context, family_id, "⏰ Прошёл час, а прогулки так и не было — не забудьте!")


# ---------- Режим 'interval' ----------

async def send_interval_reminder(context: ContextTypes.DEFAULT_TYPE):
    family_id = context.job.data
    family = db.get_family(family_id)
    if family is None:
        return

    last_walk = db.get_last_walk(family_id)
    interval_hours = family["interval_hours"] or DEFAULT_INTERVAL_HOURS
    if last_walk:
        elapsed = datetime.now(timezone.utc) - last_walk["walked_at"]
        if elapsed < timedelta(hours=interval_hours) - timedelta(minutes=1):
            # прогулку уже записали позже, чем предполагал этот job — следующий
            # тик reconcile_reminders пересчитает актуальное время сам
            return

    await send_to_family(context, family_id, f"🐾 Время выгулять {family['pet_name']}!")
    schedule_once(context, send_nudge, 3600, f"nudge_interval_{family_id}", family_id)


def schedule_interval_reminder(context: ContextTypes.DEFAULT_TYPE, family: dict):
    family_id = family["id"]
    last_walk = db.get_last_walk(family_id)
    interval_hours = family["interval_hours"] or DEFAULT_INTERVAL_HOURS
    base_time = last_walk["walked_at"] if last_walk else family["created_at"]
    target = base_time + timedelta(hours=interval_hours)
    delay = (target - datetime.now(timezone.utc)).total_seconds()

    schedule_once(context, send_interval_reminder, delay, f"reminder_interval_{family_id}", family_id)


# ---------- Режим 'fixed' ----------

async def send_fixed_before(context: ContextTypes.DEFAULT_TYPE):
    family_id = context.job.data
    family = db.get_family(family_id)
    if family:
        await send_to_family(context, family_id, f"🐾 Через час пора выгулять {family['pet_name']}!")


async def send_fixed_at(context: ContextTypes.DEFAULT_TYPE):
    family_id = context.job.data
    family = db.get_family(family_id)
    if family is None:
        return
    await send_to_family(context, family_id, f"🐾 Время выгулять {family['pet_name']}!")
    schedule_once(context, send_nudge, 3600, f"nudge_fixed_{family_id}", family_id)


def schedule_fixed_reminders(context: ContextTypes.DEFAULT_TYPE, family_id: int, time_of_day):
    time_str = time_of_day.strftime("%H:%M")
    before_time = (datetime.combine(datetime.today(), time_of_day) - timedelta(hours=1)).time()

    context.job_queue.run_daily(
        send_fixed_before,
        time=before_time,
        data=family_id,
        name=f"reminder_fixed_before_{family_id}_{time_str}",
    )
    context.job_queue.run_daily(
        send_fixed_at,
        time=time_of_day,
        data=family_id,
        name=f"reminder_fixed_at_{family_id}_{time_str}",
    )


# ---------- Периодическая сверка расписания с БД ----------

async def reconcile_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Единственный источник правды — Postgres, а не память процесса job_queue.
    Каждый тик полностью пересобирает управляемые job'ы (reminder_interval_*,
    reminder_fixed_*) из текущего состояния семей/времён — так расписание не
    расходится с прогулками и настройками, которые пишет api-сервис в другом
    процессе. Вызывается и из post_init при рестарте, и периодически (run_repeating)."""
    for job in context.job_queue.jobs():
        if job.name and (job.name.startswith("reminder_interval_") or job.name.startswith("reminder_fixed_")):
            job.schedule_removal()

    families = db.get_all_families()
    for family in families:
        if family["reminder_mode"] == "interval":
            schedule_interval_reminder(context, family)
        else:
            for time_of_day in db.get_reminder_times(family["id"]):
                schedule_fixed_reminders(context, family["id"], time_of_day)

    if families:
        logger.info("Сверка напоминаний: %d семей", len(families))


async def post_init(application: Application):
    """При старте (в том числе после перезапуска хостингом) сразу приводим
    расписание в соответствие с БД, не дожидаясь первого периодического тика."""
    await reconcile_reminders(application)


# ---------- Запуск ----------

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не найден BOT_TOKEN. Скопируйте .env.example в .env и вставьте туда токен от @BotFather."
        )
    if not MINIAPP_URL:
        raise RuntimeError(
            "Не найден MINIAPP_URL. Укажите в .env публичный адрес api-сервиса (он же отдаёт Mini App)."
        )

    db.init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))

    app.job_queue.run_repeating(reconcile_reminders, interval=RECONCILE_INTERVAL, first=RECONCILE_INTERVAL)

    logger.info("Бот запущен, жду сообщений...")
    app.run_polling()


if __name__ == "__main__":
    main()
