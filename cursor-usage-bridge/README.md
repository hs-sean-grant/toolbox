# Cursor Usage Bridge

A **token-less** Chrome extension that reads your personal Cursor usage from your existing **cursor.com browser session** and posts it to your **local** dashboard ingest endpoint.

No `WorkosCursorSessionToken` file. No env vars. The session cookie stays in Chrome's cookie jar (httpOnly — not readable by local scripts or agents). Only **usage data** lands on disk.

## Why a browser extension?

A page served from `127.0.0.1` (your command center) **cannot** credentialed-fetch `cursor.com` (CORS + httpOnly cookies). The fetch must run **on cursor.com** (extension or bookmarklet), then POST raw payloads to `http://127.0.0.1:8799/ingest` on loopback.

```
cursor.com (your session)  →  extension fetch  →  POST /ingest  →  usage.json  →  dashboard + agents
```

## Install (load unpacked)

1. Start a local server that exposes `/ingest` on `127.0.0.1:8799`. Either:
   ```bash
   # Sibling tool in this repo (token-less ingest server + dashboard):
   cd ../cursor-usage && docker compose up -d
   ```
   …or point the extension at any other compatible ingest endpoint (e.g. an
   Obsidian command center running `server.py` on the same port).
2. Open Chrome → `chrome://extensions`
3. Enable **Developer mode**
4. **Load unpacked** → select this folder (`cursor-usage-bridge/`)
5. Ensure you're logged into [cursor.com](https://cursor.com) in the same Chrome profile
6. Optional: open extension **Options** to set ingest URL / sync interval (default `http://127.0.0.1:8799/ingest`, every 10 min)

The extension syncs on install and on each alarm. Check the dashboard **Cursor usage** panel — it should update within a minute.

## One-shot: bookmarklet

See [bookmarklet.md](bookmarklet.md) for a zero-install bookmark you click while on cursor.com.

## What gets sent where

| Destination | Data |
|-------------|------|
| `cursor.com` (GET/POST, with your session cookie) | Fetches `/api/usage`, `/api/usage-summary`, events |
| `127.0.0.1:8799/ingest` (POST) | Raw JSON `{ usage, summary, events }` — transformed server-side |
| Nowhere else | Extension has no external telemetry |

## Privacy & security

- Your Cursor session cookie **never** leaves Chrome — only API **responses** are forwarded to loopback.
- The ingest server binds **127.0.0.1 only** — not reachable from other machines.
- Unofficial Cursor APIs — may change without notice.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Panel shows "waiting for data" | Log into cursor.com in this Chrome profile; reload extension |
| Ingest fails | Ensure the ingest server (`cursor-usage` or `server.py`) is running on the ingest port |
| Wrong port | Update ingest URL in extension Options (and ensure `host_permissions` covers your port) |

## Related tools

- **[cursor-usage/](../cursor-usage/)** — the token-less ingest server + dashboard this bridge feeds (`POST /ingest` → `usage.json`)
- **Obsidian command center** — an alternative consumer that runs `server.py` with the same `/ingest` contract
