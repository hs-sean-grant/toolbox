# Cursor Usage — local, token-less building block

A **self-contained, per-user** ingest server + dashboard for your personal Cursor
usage. It is **completely token-less**: no `WorkosCursorSessionToken`, no env
secret, nothing to leak. The authenticated fetch runs in **your browser** (via the
companion [`cursor-usage-bridge/`](../cursor-usage-bridge/) extension/bookmarklet),
which POSTs the raw payloads to this server's `/ingest`. The server transforms them
and exposes:

- A small **web dashboard** (`http://localhost:8799`)
- A stable **`usage.json` contract** you can `curl` into your own dashboard, agent, or alerting

```
cursor.com (your session)  →  bridge fetch  →  POST /ingest  →  usage.json  →  dashboard + agents
```

The session cookie **never leaves Chrome** (httpOnly — not readable by local scripts
or agents). Only usage **data** lands on disk. Each teammate runs it locally.

> **Caveat:** Cursor does not publish these APIs. Endpoints and field shapes can change without notice. This tool is best-effort.

## What it shows

One unified billing-cycle story (not two equal bars):

1. **Period usage** — primary bar for the active constraint:
   - **Included requests** (`GET /api/usage` → `gpt-4.numRequests` / `maxRequestUsage`, matches the web UI's 500/500) until exhausted
   - Then **on-demand spend** (`GET /api/usage-summary` → cents / $ cap)
2. **Burn-rate** — velocity vs sustainable budget, projected cap % by reset, red pulse when outpacing or at the wall
3. **Today heat gauge** — cold / normal / hot / on fire vs your cycle daily average (centered on 1.0×)
4. **Session delta** — on-demand $ since this server's first sync (snapshot deltas)

## Quick start (Docker)

```bash
cd cursor-usage
docker compose up -d
open http://localhost:8799     # shows "waiting for data" until the bridge syncs
```

Then feed it token-lessly — pick one:

- **Extension (auto, recommended):** load [`cursor-usage-bridge/`](../cursor-usage-bridge/) unpacked in Chrome. It syncs on install and every ~10 min from your logged-in cursor.com session.
- **Bookmarklet (one-shot):** click it while on a cursor.com tab — see [`cursor-usage-bridge/bookmarklet.md`](../cursor-usage-bridge/bookmarklet.md).

The dashboard updates within a minute of the first sync. Stop with `docker compose down`.

> The bridge defaults to `http://127.0.0.1:8799/ingest`. If you change `PORT`, update the bridge's ingest URL to match (extension Options, or the bookmarklet source).

## Quick start (bare, no Docker)

```bash
cd cursor-usage
# optional: export PORT=8799 DATA_DIR=./data HOST=127.0.0.1
python3 app.py
```

Open `http://localhost:8799`, then run the bridge/bookmarklet. Data files land in
`./data/usage.json` and `./data/usage_history.json`.

## Consume just the data

While the server is running:

```bash
curl -s http://localhost:8799/usage.json | python3 -m json.tool
```

Or read the file directly: `./data/usage.json` (bare) or from the Docker volume. The
page refreshes every ~45s from the cached JSON; freshness depends on the bridge's
sync cadence (~10 min by default).

---

## `usage.json` output contract

Written on every ingest to `DATA_DIR/usage.json`. All monetary **`used` / `limit` / `*Cents` fields are integer cents** unless noted. Display strings (`*Display`) are pre-formatted for UI.

### Top-level

| Field | Type | Meaning |
|-------|------|---------|
| `asOf` | string | Local timestamp `YYYY-MM-DD HH:MM` of this snapshot |
| `error` | string? | Present when no data has been ingested or a payload was invalid — UI should show "waiting for data" |
| `membershipType` | string? | e.g. `enterprise`, `pro` |
| `cycleStart` | string? | Billing cycle start date `YYYY-MM-DD` (UTC calendar date from API) |
| `cycleEnd` | string? | Billing cycle end / reset date |
| `daysElapsed` | number? | Days since cycle start |
| `daysRemaining` | number? | Days until reset |
| `cycleDays` | number? | Total cycle length in days |
| `autoModelMessage` | string? | Cursor's auto-model banner text, when present |

### `period` — primary bar (active constraint)

| Field | Type | Meaning |
|-------|------|---------|
| `phase` | string | `included` \| `on-demand` \| `included-exhausted` \| `unknown` |
| `label` | string | UI label, e.g. `"On-demand spend"` |
| `unit` | string | `requests` \| `usd` \| `unknown` |
| `used` | number? | Raw used amount (requests count or cents) |
| `limit` | number? | Raw cap (requests or cents) |
| `usedDisplay` | string? | Human label, e.g. `"$16.55 / $1,000.00"` |
| `limitDisplay` | string? | Cap display string |
| `pct` | number? | `used/limit × 100`, capped at 100 for bar width |
| `perDay` | number? | Average burn rate this cycle (requests/day or cents/day) |
| `budgetPerDay` | number? | Sustainable rate to land exactly on cap at reset |
| `perDayDisplay` | string? | Formatted burn rate |
| `budgetPerDayDisplay` | string? | Formatted sustainable rate |
| `projected` | number? | Linear projection to end of cycle at current pace |
| `projectedPct` | number? | Projected % of cap by reset |
| `daysToWall` | number? | Days until cap at current pace |
| `wallDate` | string? | Estimated wall date `YYYY-MM-DD` |
| `hitsWallBeforeReset` | boolean | True if wall comes before cycle reset |
| `atCap` | boolean | True if already at cap |
| `outpacing` | boolean | True if at cap OR hitting wall before reset (triggers red flash) |

### `included` — request-count cap (from `/api/usage`)

| Field | Type | Meaning |
|-------|------|---------|
| `used` | number | `gpt-4.numRequests` (may exceed limit when over-cap) |
| `limit` | number | `gpt-4.maxRequestUsage` (typically 500) |
| `pct` | number | Percent of included cap |
| `exhausted` | boolean | `used >= limit` |
| `atCap` | boolean | Same as exhausted |
| `remaining` | number | `max(0, limit - used)` |

### `onDemand` — dollar cap (from `/api/usage-summary`)

| Field | Type | Meaning |
|-------|------|---------|
| `enabled` | boolean | On-demand billing active |
| `usedCents` | number? | Cents spent this cycle |
| `limitCents` | number? | Cap in cents (e.g. 100000 = $1,000) |
| `usedDisplay` | string? | e.g. `"$16.55"` |
| `limitDisplay` | string? | e.g. `"$1,000.00"` |
| `pct` | number? | Percent of on-demand cap |

### `today` — local calendar day

| Field | Type | Meaning |
|-------|------|---------|
| `requests` | number? | Sum of `requestsCosts` from today's events (only when events were included in the ingest) |
| `spendCents` | number? | Sum of `chargedCents` from today's events, or on-demand delta since local midnight |
| `spendDisplay` | string? | Formatted on-demand spend today |
| `events` | number? | Event count today |
| `source` | string | `events-api` (bridge sent events) or `history-delta` (derived from snapshots) |
| `note` | string? | Present when using snapshot fallback |
| `heat` | object? | Today intensity gauge (see below) |

#### `today.heat`

Rates today's intensity against this cycle's average day. Prefers **request volume**
(when the bridge includes today's events); otherwise falls back to **on-demand spend**
so the gauge still renders on the spend-only path.

| Field | Type | Meaning |
|-------|------|---------|
| `level` | string | `cold` \| `normal` \| `hot` \| `onfire` |
| `index` | number | 0–3 zone index |
| `ratio` | number | today's value / `baselinePerDay` (1.0 = typical full day) |
| `basis` | string | `requests` or `spend` — which meter drove the gauge |
| `unit` | string | `requests` or `usd` (for the sub-label) |
| `baselinePerDay` | number | Average per-day this cycle (requests, or $ when spend-based) |

**Thresholds** (ratio vs baseline):

| Ratio | Level | Index |
|-------|-------|-------|
| &lt; 0.5 | cold | 0 |
| 0.5 – 1.35 | normal | 1 |
| 1.35 – 2.25 | hot | 2 |
| ≥ 2.25 | on fire | 3 |

### `session` — since this server's first sync

| Field | Type | Meaning |
|-------|------|---------|
| `spendCents` | number | On-demand cents delta since `sessionStart` |
| `spendDisplay` | string | Formatted |
| `since` | string | `sessionStart` timestamp from history file |
| `source` | string | `history-delta` |
| `note` | string? | Approximation caveat |

### Example (abbreviated)

```json
{
  "asOf": "2026-08-14 15:10",
  "membershipType": "enterprise",
  "cycleStart": "2026-08-01",
  "cycleEnd": "2026-09-01",
  "daysElapsed": 13.8,
  "daysRemaining": 17.2,
  "period": {
    "phase": "on-demand",
    "label": "On-demand spend",
    "unit": "usd",
    "used": 1655,
    "limit": 100000,
    "usedDisplay": "$16.55 / $1,000.00",
    "pct": 1.7,
    "perDayDisplay": "$1.20/day",
    "budgetPerDayDisplay": "$57.27/day",
    "projectedPct": 3.7,
    "outpacing": false,
    "atCap": false
  },
  "included": {
    "used": 507,
    "limit": 500,
    "pct": 100.0,
    "exhausted": true,
    "atCap": true,
    "remaining": 0
  },
  "onDemand": {
    "enabled": true,
    "usedCents": 1655,
    "limitCents": 100000,
    "usedDisplay": "$16.55",
    "limitDisplay": "$1,000.00",
    "pct": 1.7
  },
  "today": {
    "requests": 37,
    "spendCents": 148,
    "spendDisplay": "$1.48",
    "events": 37,
    "source": "events-api",
    "heat": {
      "level": "normal",
      "index": 1,
      "ratio": 1.01,
      "basis": "requests",
      "unit": "requests",
      "baselinePerDay": 36.7
    }
  },
  "session": {
    "spendCents": 12,
    "spendDisplay": "$0.12",
    "since": "2026-08-14 15:00",
    "source": "history-delta"
  }
}
```

## What the bridge fetches (in your browser, with your session)

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `https://cursor.com/api/usage` | Included request count (500/500) |
| GET | `https://cursor.com/api/usage-summary` | Billing cycle + on-demand $ cap |
| POST | `https://cursor.com/api/dashboard/get-filtered-usage-events` | Today's per-event spend (optional) |

The bridge bundles these into `{ usage, summary, events }` and POSTs them to `/ingest`.

## HTTP server routes

| Method | Path | Content |
|--------|------|---------|
| GET | `/` | Standalone dashboard (`index.html`) |
| GET | `/usage.json` | Latest snapshot (`Cache-Control: no-store`) |
| GET | `/health` | `ok` |
| OPTIONS | `/ingest` | CORS preflight (allows `https://cursor.com`) |
| POST | `/ingest` | `{ usage, summary, events }` → transform → `usage.json` |

## Security

- **No token anywhere.** The session cookie stays in Chrome (httpOnly); this server never sees it.
- Bind loopback for the strictest setup (`HOST=127.0.0.1`); the Docker image binds `0.0.0.0` inside the container so port mapping works — do not expose the mapped port to the public internet.
- `/ingest` only accepts a CORS preflight from `https://cursor.com` and writes usage data locally — it has no auth of its own, so keep the port on loopback.
- Never commit `data/` or generated `*.json` (see `.dockerignore`).

## License / warranty

Unofficial tooling, no affiliation with Cursor. Use at your own risk.
