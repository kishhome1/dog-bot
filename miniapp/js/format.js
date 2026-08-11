// format.js — форматирование дат/длительностей и таблица наград (ТЗ, раздел 5/7).

export const DURATION_OPTIONS = [
  { minutes: 10, label: "10 мин", tier: "neutral" },
  { minutes: 20, label: "20 мин", tier: "neutral" },
  { minutes: 30, label: "30 мин", tier: "bronze" },
  { minutes: 45, label: "45 мин", tier: "bronze" },
  { minutes: 60, label: "1 ч", tier: "silver" },
  { minutes: 90, label: "1.5 ч", tier: "gold" },
  { minutes: 120, label: "2 ч ⭐", tier: "gold-top" },
];

const BADGE_CLASS_BY_TIER = {
  neutral: "badge-neutral",
  bronze: "badge-bronze",
  silver: "badge-silver",
  gold: "badge-gold",
  "gold-top": "badge-gold-top",
};

export function tierForDuration(minutes) {
  return DURATION_OPTIONS.find((o) => o.minutes === minutes)?.tier || null;
}

export function durationLabel(minutes) {
  return DURATION_OPTIONS.find((o) => o.minutes === minutes)?.label || `${minutes} мин`;
}

export function badgeClassForDuration(minutes) {
  return BADGE_CLASS_BY_TIER[tierForDuration(minutes)] || "badge-neutral";
}

function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function formatTime(isoString) {
  return new Date(isoString).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function dayHeadingFor(isoString) {
  const d = new Date(isoString);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);

  if (isSameDay(d, today)) return "СЕГОДНЯ";
  if (isSameDay(d, yesterday)) return "ВЧЕРА";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" }).toUpperCase();
}

export function formatShortDate(isoOrDateString) {
  return new Date(isoOrDateString).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

export function initial(name) {
  return (name || "?").trim().charAt(0).toUpperCase();
}

export function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

export function daysRemainingLabel(days) {
  if (days < 0) return `Просрочено на ${Math.abs(days)} дн.`;
  if (days === 0) return "Сегодня";
  if (days % 30 === 0 && days >= 60) return `через ${days / 30} мес`;
  return `через ${days} дн.`;
}
