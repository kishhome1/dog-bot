// settings.js — вкладка «Настройки»: профиль собаки, напоминания, семья/инвайт,
// экспорт истории в CSV.

import { api } from "./api.js";
import { state } from "./state.js";
import { createTimeListEditor } from "./time-list.js";
import { escapeHtml, initial } from "./format.js";

let settingsMode = "fixed";
const timeListEditor = createTimeListEditor("settings-time-list", "settings-btn-add-time", ["07:00"]);

function applyModeUI() {
  document.getElementById("settings-params-fixed").classList.toggle("hidden", settingsMode !== "fixed");
  document.getElementById("settings-params-interval").classList.toggle("hidden", settingsMode !== "interval");
  document.querySelectorAll("#settings-mode-switch .mode-card").forEach((c) => {
    c.classList.toggle("selected", c.dataset.mode === settingsMode);
  });
  timeListEditor.render();
}

function renderMembers() {
  const list = document.getElementById("settings-members-list");
  list.innerHTML = "";
  state.members.forEach((m, idx) => {
    const color = idx === 1 ? "var(--color-avatar-2)" : "var(--color-avatar-1)";
    const row = document.createElement("div");
    row.className = "settings-member-row";
    row.innerHTML = `
      <div class="avatar" style="background:${color}">${initial(m.display_name)}</div>
      <div class="settings-member-name">${escapeHtml(m.display_name)}</div>
    `;
    list.appendChild(row);
  });
}

export async function loadSettings() {
  const auth = await api.auth();
  state.petName = auth.pet_name;
  state.petSex = auth.pet_sex;
  state.reminderMode = auth.reminder_mode;
  state.intervalHours = auth.interval_hours;
  state.members = auth.members;

  document.getElementById("settings-pet-name").value = auth.pet_name || "";
  document.querySelectorAll("#settings-pet-sex-switch .segmented-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.sex === auth.pet_sex);
  });

  settingsMode = auth.reminder_mode || "fixed";
  document.getElementById("settings-input-interval-hours").value = auth.interval_hours || 8;
  timeListEditor.setTimes(auth.reminder_times && auth.reminder_times.length ? auth.reminder_times : ["07:00"]);
  applyModeUI();

  document.getElementById("settings-invite-link-text").textContent = auth.invite_url || "";
  renderMembers();
}

async function saveProfile() {
  const petName = document.getElementById("settings-pet-name").value.trim();
  if (!petName) {
    alert("Укажите кличку");
    return;
  }
  const activeSexBtn = document.querySelector("#settings-pet-sex-switch .segmented-item.active");

  try {
    const auth = await api.updateProfile({
      pet_name: petName,
      pet_sex: activeSexBtn ? activeSexBtn.dataset.sex : "female",
    });
    state.petName = auth.pet_name;
    state.petSex = auth.pet_sex;
  } catch (e) {
    console.error(e);
    alert("Не получилось сохранить профиль, попробуйте ещё раз.");
  }
}

async function saveReminders() {
  const payload = { reminder_mode: settingsMode };
  if (settingsMode === "fixed") {
    payload.times = timeListEditor.getTimes();
  } else {
    payload.interval_hours = Number(document.getElementById("settings-input-interval-hours").value) || 8;
  }

  try {
    const auth = await api.updateReminders(payload);
    state.reminderMode = auth.reminder_mode;
    state.intervalHours = auth.interval_hours;
  } catch (e) {
    console.error(e);
    alert("Не получилось сохранить напоминания, попробуйте ещё раз.");
  }
}

async function downloadCsv(fetchFn, filename) {
  try {
    const blob = await fetchFn();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error(e);
    alert("Не получилось скачать файл, попробуйте ещё раз.");
  }
}

export function initSettings() {
  document.querySelectorAll("#settings-pet-sex-switch .segmented-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      document
        .querySelectorAll("#settings-pet-sex-switch .segmented-item")
        .forEach((b) => b.classList.toggle("active", b === btn));
    });
  });

  document.querySelectorAll("#settings-mode-switch .mode-card").forEach((card) => {
    card.addEventListener("click", () => {
      settingsMode = card.dataset.mode;
      applyModeUI();
    });
  });

  document.getElementById("btn-save-profile").addEventListener("click", saveProfile);
  document.getElementById("btn-save-reminders").addEventListener("click", saveReminders);

  document.getElementById("settings-btn-share-invite").addEventListener("click", () => {
    const inviteUrl = document.getElementById("settings-invite-link-text").textContent;
    if (!inviteUrl) return;
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(inviteUrl)}&text=${encodeURIComponent(
      "Присоединяйся к уходу за собакой в Barbos 🐕"
    )}`;
    if (window.Telegram?.WebApp?.openTelegramLink) {
      window.Telegram.WebApp.openTelegramLink(shareUrl);
    } else {
      window.open(shareUrl, "_blank");
    }
  });

  document.getElementById("btn-export-walks").addEventListener("click", () =>
    downloadCsv(api.exportWalksCsv, "barbos_walks.csv")
  );
  document.getElementById("btn-export-treatments").addEventListener("click", () =>
    downloadCsv(api.exportTreatmentsCsv, "barbos_treatments.csv")
  );
}
