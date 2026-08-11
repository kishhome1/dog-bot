"""api/constants.py — константы категорий обработок и порогов срочности.

Интервалы — не медицинская рекомендация, а разумные дефолты для прогресс-бара
(ТЗ, раздел 3, примечания): клещи ~30 дней, глистогонное ~90, прививка ~365,
для 'other' — дефолт 30.
"""

from datetime import date

TREATMENT_INTERVALS = {
    "ticks": 30,
    "deworming": 90,
    "vaccine": 365,
    "other": 30,
}

TREATMENT_LABELS = {
    "ticks": "Клещи",
    "deworming": "Глистогонное",
    "vaccine": "Прививка",
}

# Бейдж жёлтый ("скоро"), если до дедлайна осталось не больше этого числа дней.
URGENCY_SOON_DAYS = 7


def compute_status(category: str, treated_on: date) -> dict:
    """Возвращает {days_remaining, status, progress_percent} — status: 'ok' | 'soon' | 'overdue'.
    progress_percent — сколько от интервала уже прошло (для прогресс-бара карточки), 0..100."""
    interval_days = TREATMENT_INTERVALS.get(category, TREATMENT_INTERVALS["other"])
    elapsed_days = (date.today() - treated_on).days
    days_remaining = interval_days - elapsed_days

    if days_remaining < 0:
        status = "overdue"
    elif days_remaining <= URGENCY_SOON_DAYS:
        status = "soon"
    else:
        status = "ok"

    progress_percent = max(0, min(100, round(100 * elapsed_days / interval_days)))

    return {"days_remaining": days_remaining, "status": status, "progress_percent": progress_percent}
