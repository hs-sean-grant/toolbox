#!/usr/bin/env python3
"""Cursor usage poller + tiny HTTP server (stdlib only).

Polls Cursor's unofficial usage endpoints and serves usage.json + a standalone
dashboard. Each user runs with their own WorkosCursorSessionToken.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DAY = 86400.0
USER_AGENT = "cursor-usage-tool/1.0"

DEFAULT_DATA_DIR = os.environ.get("DATA_DIR") or str(APP_DIR / "data")
DEFAULT_PORT = int(os.environ.get("PORT", "8799"))
DEFAULT_INTERVAL = int(os.environ.get("USAGE_INTERVAL", "600"))
INDEX_PATH = APP_DIR / "index.html"


def resolve_token() -> str | None:
    env = os.environ.get("CURSOR_SESSION_TOKEN", "").strip()
    if env:
        return env
    candidates = [
        os.environ.get("CURSOR_TOKEN_FILE"),
        "/run/secrets/cursor_token",
        os.path.expanduser("~/.config/cursor-usage/token"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                return Path(path).read_text(encoding="utf-8").strip()
            except OSError:
                continue
    return None


def api_headers(token: str) -> dict[str, str]:
    return {
        "Cookie": "WorkosCursorSessionToken=" + token,
        "Origin": "https://cursor.com",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }


def api_get(url: str, token: str):
    req = urllib.request.Request(url, headers=api_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def api_post(url: str, body: dict, token: str):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={**api_headers(token), "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def as_epoch(v):
    if isinstance(v, (int, float)):
        return v / 1000.0 if v > 1e11 else float(v)
    if isinstance(v, str):
        try:
            return datetime.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    return None


def fmt_usd(cents):
    if cents is None:
        return None
    return f"${cents / 100:,.2f}"


def load_history(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_history(path: Path, h):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2)


def parse_requests(usage_api):
    if not usage_api:
        return None
    bucket = usage_api.get("gpt-4") or usage_api.get("gpt-4o") or {}
    if not bucket and usage_api:
        for v in usage_api.values():
            if isinstance(v, dict) and "maxRequestUsage" in v:
                bucket = v
                break
    used = bucket.get("numRequests")
    if used is None:
        used = bucket.get("numRequestsTotal")
    limit = bucket.get("maxRequestUsage")
    if used is None or limit is None:
        return None
    pct = round(min(100.0, used / limit * 100), 1) if limit else None
    return {
        "used": int(used),
        "limit": int(limit),
        "pct": pct,
        "exhausted": bool(used >= limit),
        "atCap": bool(used >= limit),
        "remaining": max(0, int(limit) - int(used)),
    }


def wall_from_rate(used, limit, per_day, elapsed, remaining, cycle_days, now):
    if limit is None or limit <= 0 or used is None:
        return {}
    pct = min(100.0, used / limit * 100)
    per_day = per_day if per_day is not None else ((used / elapsed) if elapsed and elapsed > 0 else None)
    projected = (per_day * cycle_days) if (per_day is not None and cycle_days) else None
    days_to_wall = wall_date = None
    if per_day and per_day > 0 and used < limit:
        days_to_wall = (limit - used) / per_day
        wall_date = time.strftime("%Y-%m-%d", time.localtime(now + days_to_wall * DAY))
    budget = ((limit - used) / remaining) if (remaining and remaining > 0 and used < limit) else None
    hits = bool(days_to_wall is not None and remaining is not None and days_to_wall < remaining)
    at_wall = bool(used >= limit)
    return {
        "pct": round(pct, 1),
        "perDay": round(per_day, 3) if per_day is not None else None,
        "budgetPerDay": round(budget, 3) if budget is not None else None,
        "projected": round(projected, 1) if projected is not None else None,
        "projectedPct": round(projected / limit * 100, 1) if (projected is not None and limit) else None,
        "daysToWall": round(days_to_wall, 1) if days_to_wall is not None else None,
        "wallDate": wall_date,
        "hitsWallBeforeReset": hits,
        "atCap": at_wall,
        "outpacing": bool(at_wall or hits),
    }


def sum_today_events(token: str, max_pages=15):
    today = datetime.date.today()
    total_cents = 0
    total_requests = 0
    event_count = 0
    page = 1
    while page <= max_pages:
        data = api_post(
            "https://cursor.com/api/dashboard/get-filtered-usage-events",
            {"pageSize": 100, "page": page},
            token,
        )
        events = data.get("usageEventsDisplay") or []
        if not events:
            break
        stop = False
        for ev in events:
            ts = int(ev.get("timestamp") or 0)
            dt = datetime.datetime.fromtimestamp(ts / 1000)
            if dt.date() < today:
                stop = True
                break
            if dt.date() == today:
                event_count += 1
                total_cents += int(ev.get("chargedCents") or 0)
                total_requests += int(ev.get("requestsCosts") or 0)
        if stop:
            break
        page += 1
    if event_count == 0:
        return None
    return {
        "requests": total_requests,
        "spendCents": total_cents,
        "spendDisplay": fmt_usd(total_cents),
        "events": event_count,
        "source": "events-api",
    }


def snapshot_delta(history, key, current, since_ts_str):
    snaps = history.get("snapshots") or []
    if not snaps:
        return None
    since = None
    for s in snaps:
        if s.get("ts", "") >= since_ts_str:
            since = s
            break
    if since is None:
        since = snaps[0]
    base = since.get(key)
    if base is None or current is None:
        return None
    return max(0, current - base)


def update_history(history_path: Path, cycle_start, requests_used, od_cents, now_str):
    h = load_history(history_path)
    if h.get("cycleStart") != cycle_start:
        h = {"cycleStart": cycle_start, "sessionStart": now_str, "snapshots": []}
    if not h.get("sessionStart"):
        h["sessionStart"] = now_str
    snaps = h.setdefault("snapshots", [])
    if not snaps or snaps[-1].get("ts") != now_str:
        snaps.append({"ts": now_str, "requests": requests_used, "odCents": od_cents})
    if len(snaps) > 500:
        h["snapshots"] = snaps[-500:]
    save_history(history_path, h)
    return h


def today_from_history(history, od_cents, now_str):
    today_start = now_str[:10] + " 00:00"
    delta = snapshot_delta(history, "odCents", od_cents, today_start)
    if delta is None:
        return None
    return {
        "spendCents": delta,
        "spendDisplay": fmt_usd(delta),
        "source": "history-delta",
        "note": "approx — poller snapshots since local midnight",
    }


def session_from_history(history, od_cents):
    start = history.get("sessionStart")
    if not start:
        return None
    delta = snapshot_delta(history, "odCents", od_cents, start)
    if delta is None:
        return None
    return {
        "spendCents": delta,
        "spendDisplay": fmt_usd(delta),
        "since": start,
        "source": "history-delta",
        "note": "approx — since poller session start",
    }


def compute_heat(today, requests_used, elapsed):
    if not (today and today.get("requests") is not None and requests_used and elapsed and elapsed >= 0.5):
        return
    baseline = requests_used / elapsed
    if baseline <= 0:
        return
    ratio = today["requests"] / baseline
    if ratio < 0.5:
        idx, lvl = 0, "cold"
    elif ratio < 1.35:
        idx, lvl = 1, "normal"
    elif ratio < 2.25:
        idx, lvl = 2, "hot"
    else:
        idx, lvl = 3, "onfire"
    today["heat"] = {
        "level": lvl,
        "index": idx,
        "ratio": round(ratio, 2),
        "baselinePerDay": round(baseline, 1),
    }


def fetch_usage(token: str | None, data_dir: Path) -> dict:
    now = time.time()
    now_str = time.strftime("%Y-%m-%d %H:%M")
    out_path = data_dir / "usage.json"
    history_path = data_dir / "usage_history.json"

    if not token:
        result = {
            "asOf": now_str,
            "error": "no token — set CURSOR_SESSION_TOKEN or mount CURSOR_TOKEN_FILE",
        }
        data_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    try:
        summary = api_get("https://cursor.com/api/usage-summary", token)
        usage_api = api_get("https://cursor.com/api/usage", token)
    except Exception as e:
        result = {"asOf": now_str, "error": str(e)}
        data_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    def iso_date(v):
        if isinstance(v, str) and len(v) >= 10:
            return v[:10]
        return time.strftime("%Y-%m-%d", time.gmtime(as_epoch(v))) if v else None

    start = as_epoch(summary.get("billingCycleStart"))
    end = as_epoch(summary.get("billingCycleEnd"))
    cycle_start = iso_date(summary.get("billingCycleStart"))
    cycle_end = iso_date(summary.get("billingCycleEnd"))
    cycle_days = (end - start) / DAY if start and end else None
    elapsed = (now - start) / DAY if start else None
    remaining = (end - now) / DAY if end else None

    included = parse_requests(usage_api)
    iu = summary.get("individualUsage") or {}
    od = iu.get("onDemand") or {}
    od_used = od.get("used") if isinstance(od.get("used"), (int, float)) else None
    od_limit = od.get("limit") if isinstance(od.get("limit"), (int, float)) else None
    od_enabled = bool(od.get("enabled"))

    requests_used = included["used"] if included else None
    history = update_history(history_path, cycle_start, requests_used, od_used, now_str)

    today = None
    try:
        today = sum_today_events(token)
    except Exception:
        pass
    if not today:
        today = today_from_history(history, od_used, now_str)

    compute_heat(today, requests_used, elapsed)
    session = session_from_history(history, od_used)

    if included and not included.get("exhausted"):
        phase = "included"
        primary_label = "Included requests"
        primary_unit = "requests"
        used = included["used"]
        limit = included["limit"]
        used_display = f"{used:,}/{limit:,} requests"
        burn = wall_from_rate(used, limit, None, elapsed, remaining, cycle_days, now)
        burn["perDayDisplay"] = (
            f"{burn['perDay']:.1f} req/day" if burn.get("perDay") is not None else None
        )
        burn["budgetPerDayDisplay"] = (
            f"{burn['budgetPerDay']:.1f} req/day" if burn.get("budgetPerDay") is not None else None
        )
    elif od_enabled and od_limit:
        phase = "on-demand"
        primary_label = "On-demand spend"
        primary_unit = "usd"
        used = od_used or 0
        limit = od_limit
        used_display = f"{fmt_usd(used)} / {fmt_usd(limit)}"
        burn = wall_from_rate(used, limit, None, elapsed, remaining, cycle_days, now)
        burn["perDayDisplay"] = (
            f"{fmt_usd(burn['perDay'])}/day" if burn.get("perDay") is not None else None
        )
        burn["budgetPerDayDisplay"] = (
            f"{fmt_usd(burn['budgetPerDay'])}/day" if burn.get("budgetPerDay") is not None else None
        )
    elif included:
        phase = "included-exhausted"
        primary_label = "Included requests"
        primary_unit = "requests"
        used = included["used"]
        limit = included["limit"]
        used_display = f"{used:,}/{limit:,} requests (exhausted)"
        burn = wall_from_rate(used, limit, None, elapsed, remaining, cycle_days, now)
        burn["atCap"] = True
        burn["outpacing"] = True
        burn["perDayDisplay"] = None
        burn["budgetPerDayDisplay"] = None
    else:
        phase = "unknown"
        primary_label = "Period usage"
        primary_unit = "unknown"
        used = limit = None
        used_display = "unavailable"
        burn = {}

    result = {
        "asOf": now_str,
        "membershipType": summary.get("membershipType"),
        "cycleStart": cycle_start,
        "cycleEnd": cycle_end,
        "daysElapsed": round(elapsed, 1) if elapsed is not None else None,
        "daysRemaining": round(remaining, 1) if remaining is not None else None,
        "cycleDays": round(cycle_days, 1) if cycle_days else None,
        "period": {
            "phase": phase,
            "label": primary_label,
            "unit": primary_unit,
            "used": used,
            "limit": limit,
            "usedDisplay": used_display,
            "limitDisplay": fmt_usd(limit) if primary_unit == "usd" else (str(limit) if limit else None),
            **burn,
        },
        "included": included,
        "onDemand": {
            "enabled": od_enabled,
            "usedCents": od_used,
            "limitCents": od_limit,
            "usedDisplay": fmt_usd(od_used),
            "limitDisplay": fmt_usd(od_limit),
            "pct": round(od_used / od_limit * 100, 1) if (od_used is not None and od_limit) else None,
        },
        "today": today,
        "session": session,
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


class UsageHandler(BaseHTTPRequestHandler):
    data_dir = Path(DEFAULT_DATA_DIR)
    index_bytes = INDEX_PATH.read_bytes() if INDEX_PATH.is_file() else b"<h1>index.html missing</h1>"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._respond(200, "text/html; charset=utf-8", self.index_bytes, nocache=True)
        elif path == "/usage.json":
            usage_path = self.data_dir / "usage.json"
            if usage_path.is_file():
                body = usage_path.read_bytes()
            else:
                body = json.dumps({"asOf": time.strftime("%Y-%m-%d %H:%M"), "error": "no data yet"}).encode()
            self._respond(200, "application/json", body, nocache=True)
        elif path == "/health":
            self._respond(200, "text/plain", b"ok")
        else:
            self.send_error(404)

    def _respond(self, code, content_type, body, nocache=False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if nocache:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def poll_loop(data_dir: Path, interval: int, stop: threading.Event):
    while not stop.is_set():
        try:
            token = resolve_token()
            fetch_usage(token, data_dir)
        except Exception:
            pass
        stop.wait(interval)


def main():
    data_dir = Path(DEFAULT_DATA_DIR)
    port = DEFAULT_PORT
    interval = DEFAULT_INTERVAL

    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"cursor-usage: data_dir={data_dir} port={port} interval={interval}s")

    token = resolve_token()
    if token:
        fetch_usage(token, data_dir)
        print("initial poll complete")
    else:
        fetch_usage(None, data_dir)
        print("no token — serving auth-needed state (set CURSOR_SESSION_TOKEN)")

    stop = threading.Event()
    threading.Thread(target=poll_loop, args=(data_dir, interval, stop), daemon=True).start()

    UsageHandler.data_dir = data_dir
    server = ThreadingHTTPServer(("0.0.0.0", port), UsageHandler)
    print(f"listening on http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down")
        stop.set()
        server.shutdown()


if __name__ == "__main__":
    main()
