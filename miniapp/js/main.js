// main.js — точка входа: инициализация темы, аутентификация, роутинг экранов.

import { api } from "./api.js";
import { state } from "./state.js";
import { initTelegramTheme } from "./theme.js";
import { initOnboarding, showOnboarding, handleOnboardingEntry } from "./onboarding.js";
import { initToday, loadToday, closeWalkSheet } from "./today.js";
import { initMedicine, loadMedicine, closeTreatmentForm } from "./medicine.js";
import { initStats, loadStats } from "./stats.js";
import { initSettings, loadSettings } from "./settings.js";

const MAIN_SCREENS = ["today", "walk-history", "medicine", "treatment-history", "stats", "settings"];
const NAV_SCREENS = ["today", "medicine", "stats", "settings"];
const ALL_SCREENS = ["loading", "outside-telegram", "onboarding", ...MAIN_SCREENS];

function showScreen(name) {
  for (const s of ALL_SCREENS) {
    document.getElementById(`screen-${s}`).classList.toggle("hidden", s !== name);
  }
  document.getElementById("bottom-nav").classList.toggle("hidden", !MAIN_SCREENS.includes(name));
  if (NAV_SCREENS.includes(name)) {
    document.querySelectorAll(".nav-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.screen === name);
    });
  }
}

function wireBottomNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.screen;
      showScreen(target);
      if (target === "today") loadToday();
      if (target === "medicine") loadMedicine();
      if (target === "stats") loadStats();
      if (target === "settings") loadSettings();
    });
  });
}

function wireSharedSheetBackdrop() {
  document.getElementById("sheet-backdrop").addEventListener("click", () => {
    closeWalkSheet();
    closeTreatmentForm();
  });
}

async function enterMainApp(auth, prefetchedWalks) {
  // auth может быть уже получен вызывающим кодом (boot() всегда сам делает
  // /api/auth, чтобы решить — онбординг или главный экран) — переспрашивать
  // его здесь ещё раз это лишний round-trip на каждой загрузке приложения.
  if (!auth) auth = await api.auth();
  state.familyId = auth.family_id;
  state.petName = auth.pet_name;
  state.petSex = auth.pet_sex;
  state.reminderMode = auth.reminder_mode;
  state.intervalHours = auth.interval_hours;
  state.members = auth.members;

  showScreen("today");
  await loadToday(prefetchedWalks);
}

async function boot() {
  initTelegramTheme();

  const tg = window.Telegram?.WebApp;
  const devMode = new URLSearchParams(location.search).get("dev") === "1";
  const hasInitData = !!(tg && tg.initData) || devMode;

  if (!hasInitData) {
    showScreen("outside-telegram");
    return;
  }

  wireBottomNav();
  wireSharedSheetBackdrop();
  initOnboarding();
  initToday();
  initMedicine();
  initStats();
  initSettings();

  window.addEventListener("onboarding-complete", () => {
    enterMainApp().catch((e) => {
      console.error(e);
      alert("Не получилось загрузить приложение, попробуйте переоткрыть.");
    });
  });

  let auth, walks;
  try {
    // getWalks не зависит от данных ответа /api/auth — сервер сам резолвит
    // семью пользователя по initData независимо в каждом запросе — поэтому
    // их можно слать параллельно, а не ждать auth и только потом начинать
    // walks. Если семье ещё нужен онбординг, getWalks закономерно ответит
    // 404 (нет family_id) — этот случай просто игнорируем, .catch(() => null).
    [auth, walks] = await Promise.all([api.auth(), api.getWalks({ days: 30 }).catch(() => null)]);
  } catch (e) {
    console.error(e);
    showScreen("outside-telegram");
    return;
  }

  if (auth.needs_onboarding) {
    const inviteCode = new URLSearchParams(location.search).get("invite");
    try {
      const joinedDirectly = await handleOnboardingEntry(inviteCode);
      if (joinedDirectly) {
        // только что присоединились по инвайту — предыдущий auth ещё говорит
        // needs_onboarding: true, нужен свежий ответ, тут повторный запрос оправдан
        await enterMainApp();
      }
    } catch (e) {
      console.error(e);
      showOnboarding();
    }
    return;
  }

  await enterMainApp(auth, walks ?? undefined);
}

boot();
