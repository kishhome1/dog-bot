// medicine.js — экран «Медицина» (ТЗ, раздел 8): карточки категорий, форма
// добавления обработки, экран истории категории.

import { api } from "./api.js";
import { daysRemainingLabel, escapeHtml, formatShortDate } from "./format.js";

const CATEGORY_ICON = { ticks: "🕷️", deworming: "💊", vaccine: "💉", other: "➕" };

// Дефолты только для поля формы (подсказка) — фактический срок действия
// хранится за каждой записью отдельно, пользователь может его поменять.
const DEFAULT_INTERVAL_DAYS = { ticks: 30, deworming: 90, vaccine: 365, other: 30 };

let currentHistoryCategory = null;
let currentHistoryCustomName = null;

function renderTreatmentCard(cat) {
  const card = document.createElement("div");
  card.className = "treatment-card";
  const icon = CATEGORY_ICON[cat.category] || "➕";
  const subLabel = cat.category === "other" ? `Другое · последнее — ${formatShortDate(cat.treated_on)}` : `Последняя — ${formatShortDate(cat.treated_on)}`;

  card.innerHTML = `
    <div class="treatment-card-top">
      <div class="treatment-card-name">${icon} ${escapeHtml(cat.label)}</div>
      <span class="status-badge status-${cat.status}">${daysRemainingLabel(cat.days_remaining)}</span>
    </div>
    <div class="treatment-card-sub">${subLabel}</div>
    <div class="progress-track"><div class="progress-fill" style="width:${cat.progress_percent}%"></div></div>
  `;
  card.addEventListener("click", () => openTreatmentHistoryScreen(cat));
  return card;
}

async function fetchAndRenderCategories() {
  const categories = await api.getTreatmentCategories();
  const container = document.getElementById("treatment-categories");
  container.innerHTML = "";

  if (categories.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">💊</div>
        <p class="empty-state-title">Пока нет ни одной обработки</p>
        <p class="empty-state-text">Добавь дату последней, чтобы бот считал напоминания</p>
      </div>
    `;
  } else {
    categories.forEach((cat) => container.appendChild(renderTreatmentCard(cat)));
  }
  return categories;
}

export async function loadMedicine() {
  await fetchAndRenderCategories();
}

// ---------- Экран истории категории ----------

function renderStatusCard(cat) {
  document.getElementById("treatment-status-card").innerHTML = `
    <div class="treatment-card-top">
      <div class="treatment-card-name">Следующая обработка</div>
      <span class="status-badge status-${cat.status}">${daysRemainingLabel(cat.days_remaining)}</span>
    </div>
    <div class="progress-track"><div class="progress-fill" style="width:${cat.progress_percent}%"></div></div>
  `;
}

async function renderHistoryList() {
  const rows = await api.getTreatmentHistory(currentHistoryCategory, currentHistoryCustomName);
  const listEl = document.getElementById("treatment-history-list");
  listEl.innerHTML = "";
  rows.forEach((r) => {
    const row = document.createElement("div");
    row.className = "treatment-history-row";
    row.innerHTML = `
      <span>${formatShortDate(r.treated_on)}</span>
      <span>${escapeHtml(r.drug_name || "")} <span class="pencil-icon">✎</span></span>
    `;
    row.addEventListener("click", () => openTreatmentForm(r));
    listEl.appendChild(row);
  });
}

async function openTreatmentHistoryScreen(cat) {
  currentHistoryCategory = cat.category;
  currentHistoryCustomName = cat.custom_name;
  document.getElementById("treatment-history-title").textContent = `${CATEGORY_ICON[cat.category] || ""} ${cat.label}`;
  renderStatusCard(cat);
  await renderHistoryList();

  document.getElementById("screen-medicine").classList.add("hidden");
  document.getElementById("screen-treatment-history").classList.remove("hidden");
}

// ---------- Шторка добавления/редактирования обработки ----------

let currentEditTreatmentId = null;

function toggleCustomNameField() {
  const isOther = document.getElementById("select-treatment-category").value === "other";
  document.getElementById("treatment-custom-name-field").classList.toggle("hidden", !isOther);
}

// Категорию можно менять только для НОВОЙ записи (select задизейблен при
// редактировании — см. openTreatmentForm), поэтому здесь не нужно проверять
// currentEditTreatmentId: обработчик просто не сработает в режиме правки.
function applyDefaultIntervalForCategory() {
  const category = document.getElementById("select-treatment-category").value;
  document.getElementById("input-treatment-interval-days").value = DEFAULT_INTERVAL_DAYS[category] ?? 30;
}

function openTreatmentForm(existing) {
  currentEditTreatmentId = existing ? existing.id : null;

  const categorySelect = document.getElementById("select-treatment-category");
  categorySelect.value = existing ? existing.category : currentHistoryCategory || "ticks";
  categorySelect.disabled = !!existing; // категорию у существующей записи не меняем
  toggleCustomNameField();

  document.getElementById("input-treatment-custom-name").value = existing?.custom_name || currentHistoryCustomName || "";
  document.getElementById("input-treatment-date").value = (existing?.treated_on || new Date().toISOString().slice(0, 10)).slice(0, 10);
  document.getElementById("input-treatment-drug").value = existing?.drug_name || "";
  document.getElementById("input-treatment-interval-days").value =
    existing?.interval_days ?? DEFAULT_INTERVAL_DAYS[categorySelect.value] ?? 30;

  document.getElementById("sheet-backdrop").classList.remove("hidden");
  document.getElementById("sheet-treatment").classList.remove("hidden");
}

export function closeTreatmentForm() {
  document.getElementById("sheet-backdrop").classList.add("hidden");
  document.getElementById("sheet-treatment").classList.add("hidden");
  document.getElementById("select-treatment-category").disabled = false;
  currentEditTreatmentId = null;
}

async function saveTreatment() {
  const category = document.getElementById("select-treatment-category").value;
  const customName = document.getElementById("input-treatment-custom-name").value.trim();
  const treatedOn = document.getElementById("input-treatment-date").value;
  const drugName = document.getElementById("input-treatment-drug").value.trim();
  const intervalDays = Number(document.getElementById("input-treatment-interval-days").value) || 30;

  if (category === "other" && !customName) {
    alert("Укажите название для категории «Другое»");
    return;
  }
  if (!treatedOn) {
    alert("Укажите дату");
    return;
  }

  try {
    if (currentEditTreatmentId) {
      await api.updateTreatment(currentEditTreatmentId, {
        treated_on: treatedOn,
        drug_name: drugName || null,
        interval_days: intervalDays,
        ...(category === "other" ? { custom_name: customName } : {}),
      });
    } else {
      await api.createTreatment({
        category,
        custom_name: category === "other" ? customName : null,
        treated_on: treatedOn,
        drug_name: drugName || null,
        interval_days: intervalDays,
      });
    }
    closeTreatmentForm();

    const categories = await fetchAndRenderCategories();

    const historyScreenVisible = !document.getElementById("screen-treatment-history").classList.contains("hidden");
    if (historyScreenVisible) {
      const updated = categories.find(
        (c) => c.category === currentHistoryCategory && (c.custom_name || null) === currentHistoryCustomName
      );
      if (updated) renderStatusCard(updated);
      await renderHistoryList();
    }
  } catch (e) {
    console.error(e);
    alert("Не получилось сохранить обработку, попробуйте ещё раз.");
  }
}

export function initMedicine() {
  document.getElementById("btn-add-treatment").addEventListener("click", () => {
    currentHistoryCategory = null;
    currentHistoryCustomName = null;
    openTreatmentForm(null);
  });
  document.getElementById("btn-mark-treatment").addEventListener("click", () => openTreatmentForm(null));
  document.getElementById("select-treatment-category").addEventListener("change", () => {
    toggleCustomNameField();
    applyDefaultIntervalForCategory();
  });
  document.getElementById("btn-save-treatment").addEventListener("click", saveTreatment);

  document.getElementById("btn-back-from-treatment-history").addEventListener("click", () => {
    document.getElementById("screen-treatment-history").classList.add("hidden");
    document.getElementById("screen-medicine").classList.remove("hidden");
  });
}
