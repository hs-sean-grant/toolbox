# tokenless-cursor-usage

A **completely token-less** solution for tracking your personal Cursor usage —
utilization, burn-rate, and when you'll hit the wall. No `WorkosCursorSessionToken`,
no env secret, nothing an agent or local script could leak. The authenticated fetch
runs in **your browser session**; a local server only transforms and serves the data.

```
cursor.com (your session)  →  bridge fetch  →  POST /ingest  →  usage.json  →  dashboard + agents
```

## Two parts

| Folder | Role |
|--------|------|
| [`cursor-usage/`](cursor-usage/) | **Ingest server + dashboard.** Accepts `POST /ingest`, transforms raw payloads, serves `http://localhost:8799` and a documented `usage.json`. Runs bare or in Docker. |
| [`cursor-usage-bridge/`](cursor-usage-bridge/) | **The feeder.** Chrome extension + one-shot bookmarklet that reads usage from your logged-in cursor.com session and POSTs it to the server's `/ingest`. |

## Quick start

```bash
cd cursor-usage
docker compose up -d        # dashboard on http://localhost:8799 (waits for data)
```

Then load [`cursor-usage-bridge/`](cursor-usage-bridge/) unpacked in Chrome (or use
its bookmarklet) while logged into cursor.com. Data flows in within a minute.

See each folder's README for details, the `usage.json` contract, and troubleshooting.
The session cookie never leaves Chrome (httpOnly); only usage **data** lands on disk.

> Unofficial Cursor endpoints — may change without notice. Use at your own risk.
