const DEFAULT_INGEST = "http://127.0.0.1:8799/ingest";
const DEFAULT_INTERVAL_MIN = 10;

const ingestUrl = document.getElementById("ingestUrl");
const intervalMinutes = document.getElementById("intervalMinutes");
const status = document.getElementById("status");

chrome.storage.sync.get(
  { ingestUrl: DEFAULT_INGEST, intervalMinutes: DEFAULT_INTERVAL_MIN },
  (data) => {
    ingestUrl.value = data.ingestUrl;
    intervalMinutes.value = data.intervalMinutes;
  }
);

document.getElementById("save").addEventListener("click", () => {
  const payload = {
    ingestUrl: ingestUrl.value.trim() || DEFAULT_INGEST,
    intervalMinutes: Math.max(1, parseInt(intervalMinutes.value, 10) || DEFAULT_INTERVAL_MIN),
  };
  chrome.storage.sync.set(payload, () => {
    status.hidden = false;
    setTimeout(() => { status.hidden = true; }, 2000);
  });
});
