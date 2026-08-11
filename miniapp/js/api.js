// api.js — тонкая обёртка над fetch к /api/*. Каждый запрос несёт initData
// в заголовке Authorization: "tma <initData>" — так его ожидает api/auth.py.

const API_BASE = "/api";

// fetch() сам по себе не имеет таймаута вообще — без signal/AbortController
// браузер будет ждать ответ бесконечно, если сервер просто не отвечает (а не
// возвращает ошибку). Без этого дольше REQUEST_TIMEOUT_MS зависший запрос
// оставлял бы Mini App вечно на экране загрузки — ни успеха, ни ошибки.
// Значение короткое (5с): холодный старт на Railway исключён (Sleep выключен,
// платный тариф) — таймаут не обязан покрывать пробуждение контейнера,
// только реальную сетевую/БД аномалию (см. keepalive в database.py). Здоровый
// запрос при прогретом пуле соединений укладывается в десятки-сотни мс.
const REQUEST_TIMEOUT_MS = 5000;

// Временное диагностическое логирование запросов (см. CLAUDE.md, раздел про
// производительность Mini App) — показывает в консоли, сколько запросов
// уходит при загрузке экрана, идут ли они параллельно или друг за другом,
// и сколько каждый занял. offsetMs — момент начала относительно навигации,
// по нему видно перекрытие (параллельность) визуально даже без графика.
let requestSeq = 0;

function logTiming(id, method, path, phase, extra) {
  const offsetMs = performance.now().toFixed(0);
  console.log(`[api#${id}] ${phase} ${method} ${path} @${offsetMs}ms${extra ? " " + extra : ""}`);
}

function currentInitData() {
  return window.__DEV_INIT_DATA__ || window.Telegram?.WebApp?.initData || "";
}

async function fetchWithTimeout(url, options) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (e) {
    if (e.name === "AbortError") {
      throw new Error(`Таймаут запроса (>${REQUEST_TIMEOUT_MS}ms): ${url}`);
    }
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function request(method, path, body) {
  const id = ++requestSeq;
  const startedAt = performance.now();
  logTiming(id, method, path, "→");

  const headers = { Authorization: `tma ${currentInitData()}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res;
  try {
    res = await fetchWithTimeout(`${API_BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    logTiming(id, method, path, "✗ network error/timeout", `(${(performance.now() - startedAt).toFixed(0)}ms)`);
    throw e;
  }

  const serverMs = res.headers.get("X-Response-Time-Ms");
  logTiming(
    id,
    method,
    path,
    "←",
    `status=${res.status} total=${(performance.now() - startedAt).toFixed(0)}ms${serverMs ? ` server=${serverMs}ms` : ""}`
  );

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
  const id = ++requestSeq;
  const startedAt = performance.now();
  logTiming(id, "GET", path, "→");

  let res;
  try {
    res = await fetchWithTimeout(`${API_BASE}${path}`, {
      headers: { Authorization: `tma ${currentInitData()}` },
    });
  } catch (e) {
    logTiming(id, "GET", path, "✗ network error/timeout", `(${(performance.now() - startedAt).toFixed(0)}ms)`);
    throw e;
  }
  logTiming(id, "GET", path, "←", `status=${res.status} total=${(performance.now() - startedAt).toFixed(0)}ms`);

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
