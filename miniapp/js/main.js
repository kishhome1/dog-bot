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
const ALL_SCREENS = ["loading", "outside-telegram", "load-error", "onboarding", ...MAIN_SCREENS];

// Если /api/auth не ответил с первой попытки — скорее всего api-сервис ещё
// поднимается после простоя (холодный старт на Railway), а не что-то
// сломано насовсем. Один автоматический повтор через паузу тихо проглатывает
// большинство таких случаев, не заставляя пользователя тыкать «Повторить» сам.
const AUTH_RETRY_DELAY_MS = 2500;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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

async function fetchAuthAndWalks() {
  // getWalks не зависит от данных ответа /api/auth — сервер сам резолвит
  // семью пользователя по initData независимо в каждом запросе — поэтому их
  // можно слать параллельно, а не ждать auth и только потом начинать walks.
  // Если семье ещё нужен онбординг, getWalks закономерно ответит 404 (нет
  // family_id) — этот случай просто игнорируем, .catch(() => null).
  return Promise.all([api.auth(), api.getWalks({ days: 30 }).catch(() => null)]);
}

// Отдельно от boot(), чтобы кнопка «Повторить» могла звать это же самое, а не
// весь boot() — иначе повторный boot() навешал бы все обработчики кликов
// (wireBottomNav и т.д.) ещё раз поверх уже навешанных.
async function loadMainScreen() {
  let auth, walks;
  try {
    [auth, walks] = await fetchAuthAndWalks();
  } catch (firstError) {
    // Мы точно внутри Telegram (до этой функции не доходим без initData) —
    // сюда попадает только сбой самого запроса: сеть, 5xx, или api-сервис
    // ещё не проснулся после простоя на Railway. Один тихий повтор через
    // паузу — именно то, что вручную делали пользователи, когда «чуть позже
    // само загрузилось».
    console.warn("Первая попытка /api/auth не удалась, пробую ещё раз через", AUTH_RETRY_DELAY_MS, "мс:", firstError);
    await sleep(AUTH_RETRY_DELAY_MS);
    try {
      [auth, walks] = await fetchAuthAndWalks();
    } catch (secondError) {
      console.error(secondError);
      showScreen("load-error");
      return;
    }
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

function wireLoadErrorRetry() {
  document.getElementById("btn-retry-load").addEventListener("click", () => {
    showScreen("loading");
    loadMainScreen().catch((e) => {
      console.error(e);
      showScreen("load-error");
    });
  });
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
  wireLoadErrorRetry();
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

  await loadMainScreen();
}

boot();
