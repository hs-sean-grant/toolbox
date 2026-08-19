const DEFAULT_INGEST = "http://127.0.0.1:8799/ingest";
const DEFAULT_INTERVAL_MIN = 10;

async function getSettings() {
  const stored = await chrome.storage.sync.get({
    ingestUrl: DEFAULT_INGEST,
    intervalMinutes: DEFAULT_INTERVAL_MIN,
  });
  return stored;
}

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, { ...opts, credentials: "include" });
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status} ${url}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function collectUsage() {
  const usage = await fetchJson("https://cursor.com/api/usage");
  const summary = await fetchJson("https://cursor.com/api/usage-summary");
  let events = null;
  try {
    events = await fetchJson("https://cursor.com/api/dashboard/get-filtered-usage-events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pageSize: 100, page: 1 }),
    });
  } catch (e) {
    console.warn("Cursor Usage Bridge: events fetch failed", e);
  }
  return { usage, summary, events };
}

async function postIngest(payload) {
  const { ingestUrl } = await getSettings();
  const res = await fetch(ingestUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `ingest HTTP ${res.status}`);
  }
  return data;
}

async function syncUsage(reason) {
  try {
    const payload = await collectUsage();
    const result = await postIngest(payload);
    console.log("Cursor Usage Bridge: synced", reason, result);
  } catch (e) {
    if (e.status === 401 || e.status === 403) {
      console.warn("Cursor Usage Bridge: not logged in to cursor.com — open cursor.com and sign in");
      return;
    }
    console.error("Cursor Usage Bridge: sync failed", e);
  }
}

async function scheduleAlarm() {
  const { intervalMinutes } = await getSettings();
  const period = Math.max(1, intervalMinutes);
  chrome.alarms.create("usage-sync", { periodInMinutes: period });
}

chrome.runtime.onInstalled.addListener(() => {
  scheduleAlarm();
  syncUsage("install");
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "usage-sync") syncUsage("alarm");
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync" && (changes.ingestUrl || changes.intervalMinutes)) {
    scheduleAlarm();
  }
});
