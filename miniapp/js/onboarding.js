// onboarding.js — 4 шага онбординга (ТЗ, раздел 4). Подключение второго
// участника по инвайт-коду обходит эти шаги полностью — см. tryAutoJoin().

import { api } from "./api.js";

const steps = ["name", "mode", "params", "invite"];
let petName = "";
let petSex = "female";
let mode = "fixed";
let times = ["07:00", "19:00"];
let inviteUrl = "";

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

function renderTimeList() {
  const list = document.getElementById("time-list");
  list.innerHTML = "";
  times.forEach((t, idx) => {
    const row = document.createElement("div");
    row.className = "time-row";
    row.innerHTML = `
      <input type="time" value="${t}" data-idx="${idx}" />
      <button class="remove-time" data-idx="${idx}" ${times.length <= 1 ? "disabled" : ""}>✕</button>
    `;
    list.appendChild(row);
  });

  list.querySelectorAll('input[type="time"]').forEach((input) => {
    input.addEventListener("change", (e) => {
      times[Number(e.target.dataset.idx)] = e.target.value;
    });
  });
  list.querySelectorAll(".remove-time").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      if (times.length <= 1) return;
      times.splice(Number(e.target.dataset.idx), 1);
      renderTimeList();
    });
  });
}

function resetOnboarding() {
  petName = "";
  petSex = "female";
  mode = "fixed";
  times = ["07:00", "19:00"];
  document.getElementById("input-pet-name").value = "";
  document.getElementById("btn-step-name-next").disabled = true;
  document.querySelectorAll("#pet-sex-switch .segmented-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.sex === petSex);
  });
  document.querySelectorAll(".mode-card").forEach((c) => c.classList.remove("selected"));
  document.getElementById("input-interval-hours").value = "8";
  renderTimeList();
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
  renderTimeList();
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

  document.querySelectorAll(".mode-card").forEach((card) => {
    card.addEventListener("click", () => {
      mode = card.dataset.mode;
      document.querySelectorAll(".mode-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      applyModeToParamsStep();
      showStep("params");
    });
  });

  document.getElementById("btn-add-time").addEventListener("click", () => {
    times.push("12:00");
    renderTimeList();
  });

  document.getElementById("btn-step-params-next").addEventListener("click", async () => {
    const btn = document.getElementById("btn-step-params-next");
    btn.disabled = true;
    try {
      const payload = { pet_name: petName, pet_sex: petSex, reminder_mode: mode, timezone: detectTimezone() };
      if (mode === "fixed") {
        payload.times = times;
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
