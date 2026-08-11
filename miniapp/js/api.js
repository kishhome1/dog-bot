// api.js — тонкая обёртка над fetch к /api/*. Каждый запрос несёт initData
// в заголовке Authorization: "tma <initData>" — так его ожидает api/auth.py.

const API_BASE = "/api";

function currentInitData() {
  return window.__DEV_INIT_DATA__ || window.Telegram?.WebApp?.initData || "";
}

async function request(method, path, body) {
  const headers = { Authorization: `tma ${currentInitData()}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (e) {
      /* тело не JSON — оставляем statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

async function requestBlob(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `tma ${currentInitData()}` },
  });
  if (!res.ok) throw new Error(`${res.status}: не удалось скачать файл`);
  return res.blob();
}

export const api = {
  auth: () => request("POST", "/auth"),
  createFamily: (payload) => request("POST", "/family", payload),
  joinFamily: (inviteCode) => request("POST", "/family/join", { invite_code: inviteCode }),
  updateProfile: (payload) => request("PATCH", "/family", payload),
  updateReminders: (payload) => request("PATCH", "/family/reminders", payload),

  exportWalksCsv: () => requestBlob("/export/walks"),
  exportTreatmentsCsv: () => requestBlob("/export/treatments"),

  getWalks: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request("GET", `/walks${qs ? "?" + qs : ""}`);
  },
  createWalk: (payload) => request("POST", "/walks", payload),
  updateWalk: (id, payload) => request("PATCH", `/walks/${id}`, payload),

  getTreatmentCategories: () => request("GET", "/treatments"),
  getTreatmentHistory: (category, customName) => {
    const params = { category };
    if (customName) params.custom_name = customName;
    const qs = new URLSearchParams(params).toString();
    return request("GET", `/treatments/history?${qs}`);
  },
  createTreatment: (payload) => request("POST", "/treatments", payload),
  updateTreatment: (id, payload) => request("PATCH", `/treatments/${id}`, payload),

  getStats: (period) => request("GET", `/stats?period=${period}`),
};
