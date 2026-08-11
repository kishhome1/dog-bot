// today.js — экран «Сегодня» (ТЗ, раздел 6), шторка отметки прогулки (раздел 7)
// и экран «Вся история».

import { api } from "./api.js";
import { state, avatarColorFor, displayNameFor } from "./state.js";
import {
  DURATION_OPTIONS,
  badgeClassForDuration,
  dayHeadingFor,
  durationLabel,
  escapeHtml,
  formatTime,
  initial,
} from "./format.js";

const HISTORY_PAGE_SIZE = 20;

let selectedDuration = null;
let currentEditWalkId = null;
let historyOffset = 0;

// ---------- Карточка настроения ----------

function renderMoodCard(walks) {
  const card = document.getElementById("mood-card");
  const walkBtn = document.getElementById("btn-walked");
  const fullHistoryBtn = document.getElementById("btn-full-history");
  const listEl = document.getElementById("walks-list");

  if (walks.length === 0) {
    card.innerHTML = `
      <div class="mood-avatar">🐾</div>
      <div>
        <div class="mood-text-title">Привет! Я ${state.petName}</div>
        <div class="mood-text-subtitle">Ещё не гуляли — самое время</div>
      </div>
    `;
    walkBtn.textContent = "🚶 Отметить первую прогулку";
    fullHistoryBtn.classList.add("hidden");
    listEl.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🐾</div>
        <p class="empty-state-text">Здесь появится история прогулок</p>
      </div>
    `;
    return;
  }

  walkBtn.textContent = "🚶 Выгулял";
  fullHistoryBtn.classList.remove("hidden");

  const lastWalk = walks[0];
  const threshold = state.reminderMode === "interval" ? state.intervalHours || 8 : 5;
  const hoursSince = (Date.now() - new Date(lastWalk.walked_at).getTime()) / 3600000;
  const recentlyWalked = hoursSince < threshold;

  const isMale = state.petSex === "male";
  const moodTitle = recentlyWalked
    ? `${state.petName} ${isMale ? "бодр" : "бодра"}`
    : `${state.petName} ${isMale ? "заждался" : "заждалась"}`;

  card.innerHTML = `
    <div class="mood-avatar">🐾</div>
    <div>
      <div class="mood-text-title">${moodTitle}</div>
      <div class="mood-text-subtitle">${
        recentlyWalked ? "Гуляли недавно" : `Не гуляли ${Math.floor(hoursSince)} ч.`
      }</div>
    </div>
  `;
}

// ---------- Строка прогулки ----------

function renderWalkRow(walk) {
  const row = document.createElement("div");
  row.className = "walk-row";

  const name = displayNameFor(walk.tg_user_id);
  const color = avatarColorFor(walk.tg_user_id);

  const rightHtml =
    walk.duration_minutes != null
      ? `<span class="badge ${badgeClassForDuration(walk.duration_minutes)}">${durationLabel(walk.duration_minutes)}</span>`
      : `<span class="badge-add-details">добавить детали</span>`;

  const noteHtml = walk.note
    ? `<div class="walk-row-note">📝 ${escapeHtml(walk.note)}</div>`
    : "";

  row.innerHTML = `
    <div class="avatar" style="background:${color}">${initial(name)}</div>
    <div class="walk-row-main">
      <div class="walk-row-time">${formatTime(walk.walked_at)}${walk.together ? " · 👥 вместе" : ""}</div>
      ${noteHtml}
    </div>
    <div class="walk-row-right">
      ${rightHtml}
      <span class="pencil-icon">✎</span>
    </div>
  `;
  row.addEventListener("click", () => openWalkSheet(walk));
  return row;
}

function renderWalksList(container, walks) {
  container.innerHTML = "";
  let lastHeading = null;
  for (const walk of walks) {
    const heading = dayHeadingFor(walk.walked_at);
    if (heading !== lastHeading) {
      const h = document.createElement("div");
      h.className = "day-heading";
      h.textContent = heading;
      container.appendChild(h);
      lastHeading = heading;
    }
    container.appendChild(renderWalkRow(walk));
  }
}

// ---------- Загрузка экрана «Сегодня» ----------

// prefetchedWalks — необязательный уже начатый запрос (или готовый массив),
// см. main.js: boot() шлёт /api/auth и /api/walks параллельно, а не
// последовательно, раз getWalks не зависит от данных ответа /api/auth.
export async function loadToday(prefetchedWalks) {
  const walks = prefetchedWalks !== undefined ? await prefetchedWalks : await api.getWalks({ days: 30 });
  renderMoodCard(walks);
  if (walks.length > 0) {
    renderWalksList(document.getElementById("walks-list"), walks);
  }
}

// ---------- Шторка отметки/редактирования прогулки ----------

function makeDurationBtn(opt) {
  const btn = document.createElement("div");
  btn.className = `duration-btn ${badgeClassForDuration(opt.minutes)}${opt.minutes === selectedDuration ? " selected" : ""}`;
  btn.textContent = opt.label;
  btn.addEventListener("click", () => {
    selectedDuration = selectedDuration === opt.minutes ? null : opt.minutes;
    renderDurationGrid();
  });
  return btn;
}

function renderDurationGrid() {
  const grid = document.getElementById("duration-grid");
  grid.innerHTML = "";
  DURATION_OPTIONS.slice(0, 4).forEach((opt) => grid.appendChild(makeDurationBtn(opt)));

  const row2 = document.createElement("div");
  row2.className = "duration-row-2";
  DURATION_OPTIONS.slice(4).forEach((opt) => row2.appendChild(makeDurationBtn(opt)));
  grid.appendChild(row2);
}

function openWalkSheet(walk) {
  currentEditWalkId = walk ? walk.id : null;
  selectedDuration = walk ? walk.duration_minutes : null;

  document.getElementById("walk-sheet-title").textContent = walk
    ? `Прогулка, ${formatTime(walk.walked_at)}`
    : "Прогулка отмечена ✅";
  document.getElementById("input-together").checked = walk ? walk.together : false;
  document.getElementById("input-walk-note").value = walk?.note || "";
  document.getElementById("btn-skip-walk").classList.toggle("hidden", !!walk);

  renderDurationGrid();
  document.getElementById("sheet-backdrop").classList.remove("hidden");
  document.getElementById("sheet-walk").classList.remove("hidden");
}

export function closeWalkSheet() {
  document.getElementById("sheet-backdrop").classList.add("hidden");
  document.getElementById("sheet-walk").classList.add("hidden");
  currentEditWalkId = null;
}

async function refreshAfterWalkChange() {
  closeWalkSheet();
  await loadToday();
  const historyScreen = document.getElementById("screen-walk-history");
  if (!historyScreen.classList.contains("hidden")) {
    historyOffset = 0;
    await loadWalkHistory(false);
  }
}

async function saveWalk() {
  const payload = {
    duration_minutes: selectedDuration,
    together: document.getElementById("input-together").checked,
    note: document.getElementById("input-walk-note").value.trim() || null,
  };
  try {
    if (currentEditWalkId) {
      await api.updateWalk(currentEditWalkId, payload);
    } else {
      await api.createWalk(payload);
    }
    await refreshAfterWalkChange();
  } catch (e) {
    console.error(e);
    alert("Не получилось сохранить прогулку, попробуйте ещё раз.");
  }
}

async function skipWalk() {
  try {
    await api.createWalk({ together: false });
    await refreshAfterWalkChange();
  } catch (e) {
    console.error(e);
    alert("Не получилось записать прогулку, попробуйте ещё раз.");
  }
}

// ---------- Экран «Вся история» ----------

async function loadWalkHistory(append) {
  const walks = await api.getWalks({ days: 3650, limit: HISTORY_PAGE_SIZE, offset: historyOffset });
  const listEl = document.getElementById("walk-history-list");
  if (!append) listEl.innerHTML = "";

  let lastHeading = append ? listEl.dataset.lastHeading || null : null;
  for (const walk of walks) {
    const heading = dayHeadingFor(walk.walked_at);
    if (heading !== lastHeading) {
      const h = document.createElement("div");
      h.className = "day-heading";
      h.textContent = heading;
      listEl.appendChild(h);
      lastHeading = heading;
    }
    listEl.appendChild(renderWalkRow(walk));
  }
  listEl.dataset.lastHeading = lastHeading || "";

  document.getElementById("btn-load-more-walks").classList.toggle("hidden", walks.length < HISTORY_PAGE_SIZE);
  historyOffset += walks.length;
}

// ---------- Инициализация обработчиков ----------

export function initToday() {
  document.getElementById("btn-walked").addEventListener("click", () => openWalkSheet(null));
  document.getElementById("btn-save-walk").addEventListener("click", saveWalk);
  document.getElementById("btn-skip-walk").addEventListener("click", skipWalk);

  document.getElementById("btn-full-history").addEventListener("click", async () => {
    document.getElementById("screen-today").classList.add("hidden");
    document.getElementById("screen-walk-history").classList.remove("hidden");
    historyOffset = 0;
    await loadWalkHistory(false);
  });
  document.getElementById("btn-back-from-history").addEventListener("click", () => {
    document.getElementById("screen-walk-history").classList.add("hidden");
    document.getElementById("screen-today").classList.remove("hidden");
  });
  document.getElementById("btn-load-more-walks").addEventListener("click", () => loadWalkHistory(true));
}
