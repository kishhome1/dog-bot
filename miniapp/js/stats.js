// stats.js — экран «Статистика» (ТЗ, раздел 9).

import { api } from "./api.js";
import { avatarColorForMemberId } from "./state.js";
import { escapeHtml, initial } from "./format.js";

let currentPeriod = "week";
const PERIOD_LABEL = { week: "неделю", month: "месяц", year: "год" };

function renderStats(data) {
  const body = document.getElementById("stats-body");

  if (data.total === 0) {
    body.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📊</div>
        <p class="empty-state-title">Пока не о чем рассказать</p>
        <p class="empty-state-text">Статистика появится после первых прогулок</p>
      </div>
    `;
    return;
  }

  const maxCount = Math.max(1, ...data.by_member.map((m) => m.walk_count));

  const byMemberHtml = data.by_member
    .map((m) => {
      const color = avatarColorForMemberId(m.member_id);
      return `
        <div class="stat-member-row">
          <div class="stat-member-name">${escapeHtml(m.display_name)}</div>
          <div class="stat-bar-track">
            <div class="stat-bar-fill" style="width:${(m.walk_count / maxCount) * 100}%;background:${color}"></div>
          </div>
          <div class="stat-member-count">${m.walk_count}</div>
        </div>
      `;
    })
    .join("");

  const rewardsHtml = data.rewards
    .map(
      (r) => `
      <div class="rewards-card">
        <div class="rewards-header">
          <div class="avatar" style="background:${avatarColorForMemberId(r.member_id)}">${initial(r.display_name)}</div>
          <div>${escapeHtml(r.display_name)}</div>
        </div>
        <div class="rewards-grid">
          <div class="reward-tile badge-gold"><div class="reward-tile-count">${r.gold}</div><div class="reward-tile-label">золото</div></div>
          <div class="reward-tile badge-silver"><div class="reward-tile-count">${r.silver}</div><div class="reward-tile-label">серебро</div></div>
          <div class="reward-tile badge-bronze"><div class="reward-tile-count">${r.bronze}</div><div class="reward-tile-label">бронза</div></div>
        </div>
      </div>
    `
    )
    .join("");

  body.innerHTML = `
    <div class="stat-total-card">
      <div class="stat-total-number">${data.total}</div>
      <div class="stat-total-label">Прогулок за ${PERIOD_LABEL[currentPeriod]}</div>
    </div>
    <div class="section-label">Кто гулял чаще</div>
    ${byMemberHtml}
    <div class="section-label">Награды за прогулки</div>
    ${rewardsHtml}
  `;
}

export async function loadStats() {
  const data = await api.getStats(currentPeriod);
  renderStats(data);
}

export function initStats() {
  document.querySelectorAll("#stats-period-switch .segmented-item").forEach((btn) => {
    btn.addEventListener("click", async () => {
      currentPeriod = btn.dataset.period;
      document.querySelectorAll("#stats-period-switch .segmented-item").forEach((b) => b.classList.toggle("active", b === btn));
      await loadStats();
    });
  });
}
