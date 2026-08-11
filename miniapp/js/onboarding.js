// onboarding.js — 4 шага онбординга (ТЗ, раздел 4). Подключение второго
// участника по инвайт-коду обходит эти шаги полностью — см. tryAutoJoin().

import { api } from "./api.js";
import { createTimeListEditor } from "./time-list.js";

const steps = ["name", "mode", "params", "invite"];
let petName = "";
let petSex = "female";
let mode = "fixed";
let inviteUrl = "";

const timeListEditor = createTimeListEditor("time-list", "btn-add-time", ["07:00", "19:00"]);

function showStep(id) {
  for (const s of steps) {
    document.getElementById(`step-${s}`).classList.toggle("hidden", s !== id);
  }
}

// Автоопределение таймзоны устройства — без отдельного шага онбординга.
// Нужно, чтобы 'fixed'-напоминания бот планировал по местному времени семьи,
// а не по UTC. Поддерживается всеми движками, на которых открывается Mini App.
function detectTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch (e) {
    return "UTC";
  }
}

function resetOnboarding() {
  petName = "";
  petSex = "female";
  mode = "fixed";
  document.getElementById("input-pet-name").value = "";
  document.getElementById("btn-step-name-next").disabled = true;
  document.querySelectorAll("#pet-sex-switch .segmented-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.sex === petSex);
  });
  document.querySelectorAll("#step-mode .mode-card").forEach((c) => c.classList.remove("selected"));
  document.getElementById("input-interval-hours").value = "8";
  timeListEditor.setTimes(["07:00", "19:00"]);
  showStep("name");
}

export function showOnboarding() {
  resetOnboarding();
  document.getElementById("screen-onboarding").classList.remove("hidden");
  document.getElementById("screen-loading").classList.add("hidden");
}

async function tryAutoJoin(inviteCode) {
  await api.joinFamily(inviteCode);
}

function applyModeToParamsStep() {
  document.getElementById("params-title").textContent =
    mode === "fixed" ? "Времена напоминаний" : "Через сколько часов";
  document.getElementById("params-fixed").classList.toggle("hidden", mode !== "fixed");
  document.getElementById("params-interval").classList.toggle("hidden", mode !== "interval");
  timeListEditor.render();
}

export function initOnboarding() {
  const nameInput = document.getElementById("input-pet-name");
  nameInput.addEventListener("input", () => {
    document.getElementById("btn-step-name-next").disabled = !nameInput.value.trim();
  });
  document.getElementById("btn-step-name-next").addEventListener("click", () => {
    petName = nameInput.value.trim();
    if (!petName) return;
    showStep("mode");
  });

  document.querySelectorAll("#pet-sex-switch .segmented-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      petSex = btn.dataset.sex;
      document.querySelectorAll("#pet-sex-switch .segmented-item").forEach((b) => b.classList.toggle("active", b === btn));
    });
  });

  document.querySelectorAll("#step-mode .mode-card").forEach((card) => {
    card.addEventListener("click", () => {
      mode = card.dataset.mode;
      document.querySelectorAll("#step-mode .mode-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      applyModeToParamsStep();
      showStep("params");
    });
  });

  document.getElementById("btn-step-params-next").addEventListener("click", async () => {
    const btn = document.getElementById("btn-step-params-next");
    btn.disabled = true;
    try {
      const payload = { pet_name: petName, pet_sex: petSex, reminder_mode: mode, timezone: detectTimezone() };
      if (mode === "fixed") {
        payload.times = timeListEditor.getTimes();
      } else {
        payload.interval_hours = Number(document.getElementById("input-interval-hours").value) || 8;
      }
      const result = await api.createFamily(payload);
      inviteUrl = result.invite_url;
      document.getElementById("invite-link-text").textContent = inviteUrl;
      showStep("invite");
    } catch (e) {
      console.error(e);
      alert("Не получилось сохранить настройки, попробуйте ещё раз.");
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById("btn-share-invite").addEventListener("click", () => {
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(inviteUrl)}&text=${encodeURIComponent(
      "Присоединяйся к уходу за собакой в Barbos 🐕"
    )}`;
    if (window.Telegram?.WebApp?.openTelegramLink) {
      window.Telegram.WebApp.openTelegramLink(shareUrl);
    } else {
      window.open(shareUrl, "_blank");
    }
  });

  document.getElementById("btn-finish-onboarding").addEventListener("click", () => {
    window.dispatchEvent(new CustomEvent("onboarding-complete"));
  });
}

export async function handleOnboardingEntry(inviteCode) {
  if (inviteCode) {
    await tryAutoJoin(inviteCode);
    return true; // сразу в главный экран, шаги онбординга не нужны
  }
  showOnboarding();
  return false;
}
