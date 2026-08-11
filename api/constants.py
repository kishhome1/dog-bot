"""api/constants.py — метки категорий обработок и порог срочности статуса.

Срок действия (interval_days) больше не захардкожен по категории — пользователь
указывает его сам при добавлении обработки (разные препараты одной категории
держат разный срок), см. TreatmentCreate.interval_days в api/schemas.py.
"""

from datetime import date

TREATMENT_LABELS = {
    "ticks": "Клещи",
    "deworming": "Глистогонное",
    "vaccine": "Прививка",
}

# Бейдж жёлтый ("скоро"), если до дедлайна осталось не больше этого числа дней.
URGENCY_SOON_DAYS = 7


def compute_status(interval_days: int, treated_on: date) -> dict:
    """Возвращает {days_remaining, status, progress_percent} — status: 'ok' | 'soon' | 'overdue'.
    progress_percent — сколько от указанного пользователем срока уже прошло
    (для прогресс-бара карточки), 0..100."""
    elapsed_days = (date.today() - treated_on).days
    days_remaining = interval_days - elapsed_days

    if days_remaining < 0:
        status = "overdue"
    elif days_remaining <= URGENCY_SOON_DAYS:
        status = "soon"
    else:
        status = "ok"

    progress_percent = max(0, min(100, round(100 * elapsed_days / interval_days))) if interval_days > 0 else 100

    return {"days_remaining": days_remaining, "status": status, "progress_percent": progress_percent}
