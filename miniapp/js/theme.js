// theme.js — синхронизация с темой Telegram (ТЗ, раздел 5: поддержка светлой
// и тёмной темы). Значения по умолчанию заданы в style.css через
// prefers-color-scheme — здесь мы просто перекрываем их темой хоста, если она есть.

export function initTelegramTheme() {
  const tg = window.Telegram?.WebApp;
  if (!tg) return;

  tg.ready();
  tg.expand();

  const apply = () => {
    const p = tg.themeParams || {};
    const root = document.documentElement.style;
    if (p.bg_color) root.setProperty("--color-bg", p.bg_color);
    if (p.secondary_bg_color) root.setProperty("--color-surface-1", p.secondary_bg_color);
    if (p.text_color) root.setProperty("--color-text", p.text_color);
    if (p.hint_color) root.setProperty("--color-text-secondary", p.hint_color);
    if (p.hint_color) root.setProperty("--color-text-muted", p.hint_color);
  };

  apply();
  tg.onEvent("themeChanged", apply);
}
