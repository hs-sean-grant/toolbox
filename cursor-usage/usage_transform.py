"""Pure transform: raw Cursor API payloads → usage.json schema (stdlib only)."""

from __future__ import annotations

import datetime
import time

DAY = 86400.0

HEAT_THRESHOLDS = (0.5, 1.35, 2.25)


def fmt_usd(cents):
    if cents is None:
        return None
    return f"${cents / 100:,.2f}"


def as_epoch(v):
    if isinstance(v, (int, float)):
        return v / 1000.0 if v > 1e11 else float(v)
    if isinstance(v, str):
        try:
            return datetime.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    return None


def iso_date(v):
    if isinstance(v, str) and len(v) >= 10:
        return v[:10]
    return time.strftime("%Y-%m-%d", time.gmtime(as_epoch(v))) if v else None


def parse_requests(usage_api):
    """Included request counts from GET /api/usage (matches web UI 500/500)."""
    if not usage_api or not isinstance(usage_api, dict):
        return None
    bucket = usage_api.get("gpt-4") or usage_api.get("gpt-4o") or {}
    if not bucket:
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


def sum_today_from_events(events_response, max_pages=15):
    """Sum today's on-demand spend from raw events API response(s)."""
    if not events_response:
        return None
    today = datetime.date.today()
    total_cents = 0
    total_requests = 0
    event_count = 0

    pages = events_response if isinstance(events_response, list) else [events_response]
    for page_idx, data in enumerate(pages):
        if page_idx >= max_pages:
            break
        if not isinstance(data, dict):
            continue
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
    snaps = (history or {}).get("snapshots") or []
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


def update_history(history, cycle_start, requests_used, od_cents, now_str):
    h = dict(history) if history else {}
    if h.get("cycleStart") != cycle_start:
        h = {"cycleStart": cycle_start, "sessionStart": now_str, "snapshots": []}
    if not h.get("sessionStart"):
        h["sessionStart"] = now_str
    snaps = list(h.setdefault("snapshots", []))
    if not snaps or snaps[-1].get("ts") != now_str:
        snaps.append({"ts": now_str, "requests": requests_used, "odCents": od_cents})
    if len(snaps) > 500:
        snaps = snaps[-500:]
    h["snapshots"] = snaps
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
    start = (history or {}).get("sessionStart")
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


def compute_heat(today, requests_used, elapsed, od_used=None):
    """Rate today's intensity vs this cycle's average day.

    Prefers request volume (needs today's request count from the events API);
    falls back to on-demand spend so the gauge still renders on the spend-only
    ("history-delta") data path. Same ratio semantics → same thresholds.
    """
    if not (today and elapsed and elapsed >= 0.5):
        return
    if today.get("requests") is not None and requests_used:
        baseline = requests_used / elapsed
        value = today["requests"]
        basis, unit, base_per_day = "requests", "requests", round(baseline, 1)
    elif today.get("spendCents") is not None and od_used:
        baseline = od_used / elapsed  # cents/day
        value = today["spendCents"]
        basis, unit, base_per_day = "spend", "usd", round(baseline / 100.0, 2)
    else:
        return
    if baseline <= 0:
        return
    ratio = value / baseline
    cold, normal, hot = HEAT_THRESHOLDS
    if ratio < cold:
        idx, lvl = 0, "cold"
    elif ratio < normal:
        idx, lvl = 1, "normal"
    elif ratio < hot:
        idx, lvl = 2, "hot"
    else:
        idx, lvl = 3, "onfire"
    today["heat"] = {
        "level": lvl,
        "index": idx,
        "ratio": round(ratio, 2),
        "basis": basis,
        "unit": unit,
        "baselinePerDay": base_per_day,
    }


def build_usage(raw_usage, raw_summary, today_events_or_none=None, history=None, now=None):
    """Transform raw Cursor payloads into usage.json dict + updated history.

    Args:
        raw_usage: GET /api/usage response dict
        raw_summary: GET /api/usage-summary response dict
        today_events_or_none: raw POST events response dict, or None
        history: prior usage_history dict (or None)
        now: epoch seconds (default: time.time())

    Returns:
        (usage_dict, new_history)
    """
    now = now if now is not None else time.time()
    now_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    history = history or {}

    if not raw_summary or not isinstance(raw_summary, dict):
        return {"asOf": now_str, "error": "missing or invalid summary payload"}, history
    if not raw_usage or not isinstance(raw_usage, dict):
        return {"asOf": now_str, "error": "missing or invalid usage payload"}, history

    start = as_epoch(raw_summary.get("billingCycleStart"))
    end = as_epoch(raw_summary.get("billingCycleEnd"))
    cycle_start = iso_date(raw_summary.get("billingCycleStart"))
    cycle_end = iso_date(raw_summary.get("billingCycleEnd"))
    cycle_days = (end - start) / DAY if start and end else None
    elapsed = (now - start) / DAY if start else None
    remaining = (end - now) / DAY if end else None

    included = parse_requests(raw_usage)
    iu = raw_summary.get("individualUsage") or {}
    od = iu.get("onDemand") or {}
    od_used = od.get("used") if isinstance(od.get("used"), (int, float)) else None
    od_limit = od.get("limit") if isinstance(od.get("limit"), (int, float)) else None
    od_enabled = bool(od.get("enabled"))

    requests_used = included["used"] if included else None
    new_history = update_history(history, cycle_start, requests_used, od_used, now_str)

    today = sum_today_from_events(today_events_or_none) if today_events_or_none else None
    if not today:
        today = today_from_history(new_history, od_used, now_str)

    compute_heat(today, requests_used, elapsed, od_used)
    session = session_from_history(new_history, od_used)

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
        "membershipType": raw_summary.get("membershipType"),
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
        "autoModelMessage": raw_summary.get("autoModelSelectedDisplayMessage"),
    }
    return result, new_history
