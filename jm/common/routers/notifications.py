"""Notification settings and enhanced reminders API."""

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse

router = APIRouter()


def _parse_offsets(offsets_json: str) -> list:
    """Parse offsets from JSON string, return list of dicts."""
    try:
        offsets = json.loads(offsets_json) if offsets_json else []
        if not isinstance(offsets, list):
            return []
        return offsets
    except (json.JSONDecodeError, TypeError):
        return []


def _offset_to_minutes(offset: dict) -> int:
    """Convert an offset dict to total minutes."""
    value = offset.get("value", 0)
    unit = offset.get("unit", "minute")
    if unit == "minute":
        return value
    elif unit == "hour":
        return value * 60
    elif unit == "day":
        return value * 1440
    elif unit == "week":
        return value * 10080
    return 0


def _compute_notify_times(target_dt: datetime, offsets: list) -> list:
    """Given a target datetime and offsets, return list of notify_at datetimes."""
    results = []
    for off in offsets:
        minutes = _offset_to_minutes(off)
        notify_at = target_dt - timedelta(minutes=minutes)
        results.append(notify_at)
    return results


# ── Notification Settings CRUD ──

@router.get("/api/notification-settings")
async def get_notification_settings(request: Request):
    """Get all notification settings for the current profile."""
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM notification_settings WHERE profile_id=?", (pid,)
        ).fetchall()
    settings = {}
    for r in rows:
        settings[r["target_type"]] = {
            "id": r["id"],
            "target_type": r["target_type"],
            "offsets": json.loads(r["offsets"]) if r["offsets"] else [],
            "enabled": bool(r["enabled"]),
        }
    # Ensure all types present
    for t in ("event", "todo", "habit", "dday"):
        if t not in settings:
            settings[t] = {"target_type": t, "offsets": [], "enabled": True}
    return JSONResponse(settings)


@router.post("/api/notification-settings")
async def save_notification_settings(request: Request):
    """Save notification settings. Body: JSON with target_type + offsets."""
    S = request.app.state
    pid = S.get_profile_id(request)
    body = await request.json()
    target_type = body.get("target_type", "")
    offsets = body.get("offsets", [])
    enabled = body.get("enabled", True)

    if target_type not in ("event", "todo", "habit", "dday"):
        return JSONResponse({"error": "Invalid target_type"}, status_code=400)

    offsets_json = json.dumps(offsets, ensure_ascii=False)
    with S.get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO notification_settings (profile_id, target_type, offsets, enabled)
            VALUES (?, ?, ?, ?)
        """, (pid, target_type, offsets_json, 1 if enabled else 0))
    return JSONResponse({"ok": True})


# ── Enhanced Reminders API ──

@router.get("/api/reminders")
async def get_reminders(request: Request):
    """Enhanced reminders with proper notify_at calculation based on user settings."""
    S = request.app.state
    pid = S.get_profile_id(request)
    now = datetime.now()
    today_str = date.today().isoformat()
    reminders = []

    with S.get_db() as conn:
        # Load notification settings
        ns_rows = conn.execute(
            "SELECT target_type, offsets, enabled FROM notification_settings WHERE profile_id=?",
            (pid,)
        ).fetchall()
        ns_map = {}
        for r in ns_rows:
            if r["enabled"]:
                ns_map[r["target_type"]] = _parse_offsets(r["offsets"])

        # Default offsets if no settings exist
        event_offsets = ns_map.get("event", [{"value": 15, "unit": "minute"}])
        todo_offsets = ns_map.get("todo", [{"value": 1, "unit": "day"}])
        dday_offsets = ns_map.get("dday", [{"value": 1, "unit": "day"}])
        habit_offsets = ns_map.get("habit", [])

        # ─── Events: use per-item override or global offset ───
        # Look ahead: max offset window (up to 7 days)
        max_event_minutes = max((_offset_to_minutes(o) for o in event_offsets), default=30)
        lookahead = now + timedelta(minutes=max_event_minutes + 60)
        lookahead_str = lookahead.strftime("%Y-%m-%d %H:%M")

        upcoming_events = conn.execute(
            "SELECT id, title, start_time, reminder_offsets FROM events "
            "WHERE profile_id=? AND start_time >= ? AND start_time <= ? "
            "ORDER BY start_time LIMIT 20",
            (pid, now.strftime("%Y-%m-%d %H:%M"), lookahead_str),
        ).fetchall()

        for ev in upcoming_events:
            st_str = ev["start_time"] or ""
            try:
                if "T" in st_str:
                    event_dt = datetime.fromisoformat(st_str[:16])
                elif " " in st_str:
                    event_dt = datetime.fromisoformat(st_str.replace(" ", "T")[:16])
                else:
                    continue
            except (ValueError, TypeError):
                continue

            # Per-item override or global
            item_offsets = _parse_offsets(ev["reminder_offsets"]) if ev["reminder_offsets"] else event_offsets
            notify_times = _compute_notify_times(event_dt, item_offsets)

            for notify_at in notify_times:
                # Only include if notify_at is within the polling window (past 5 min to future 5 min)
                diff = (notify_at - now).total_seconds()
                if -300 <= diff <= 300:
                    display_time = st_str[11:16] if len(st_str) >= 16 else st_str[:10]
                    offset_min = int((event_dt - notify_at).total_seconds() / 60)
                    if offset_min == 0:
                        body = "지금 시작"
                    elif offset_min < 60:
                        body = f"{offset_min}분 후 시작"
                    elif offset_min < 1440:
                        body = f"{offset_min // 60}시간 후 시작"
                    else:
                        body = f"{offset_min // 1440}일 후 시작"
                    reminders.append({
                        "type": "event", "id": ev["id"],
                        "title": ev["title"],
                        "body": body,
                        "url": "/calendar",
                        "time": st_str if "T" in st_str else st_str.replace(" ", "T"),
                        "notify_at": notify_at.isoformat(),
                    })

        # ─── Todos: overdue + upcoming with offsets ───
        # Overdue todos (always notify once)
        overdue = conn.execute(
            "SELECT id, title, due_date FROM todos "
            "WHERE profile_id=? AND completed=0 AND due_date < ? "
            "AND due_date IS NOT NULL AND due_date != '' "
            "ORDER BY due_date LIMIT 5",
            (pid, today_str),
        ).fetchall()
        for t in overdue:
            reminders.append({
                "type": "overdue", "id": t["id"],
                "title": t["title"],
                "body": f"마감일 지남: {t['due_date']}",
                "url": "/todos?filter=overdue",
                "time": t["due_date"] + "T09:00:00",
                "notify_at": now.isoformat(),
            })

        # Today/upcoming todos with offsets
        max_todo_minutes = max((_offset_to_minutes(o) for o in todo_offsets), default=1440)
        todo_lookahead = (now + timedelta(minutes=max_todo_minutes + 60)).strftime("%Y-%m-%d")
        upcoming_todos = conn.execute(
            "SELECT id, title, due_date, reminder_offsets FROM todos "
            "WHERE profile_id=? AND completed=0 AND due_date >= ? AND due_date <= ? "
            "AND due_date IS NOT NULL AND due_date != '' "
            "ORDER BY due_date LIMIT 10",
            (pid, today_str, todo_lookahead),
        ).fetchall()

        for t in upcoming_todos:
            try:
                todo_dt = datetime.strptime(t["due_date"], "%Y-%m-%d").replace(hour=9, minute=0)
            except (ValueError, TypeError):
                continue
            item_offsets = _parse_offsets(t["reminder_offsets"]) if t["reminder_offsets"] else todo_offsets
            notify_times = _compute_notify_times(todo_dt, item_offsets)
            for notify_at in notify_times:
                diff = (notify_at - now).total_seconds()
                if -300 <= diff <= 300:
                    if t["due_date"] == today_str:
                        body = "오늘 마감"
                    else:
                        days_left = (datetime.strptime(t["due_date"], "%Y-%m-%d").date() - date.today()).days
                        body = f"{days_left}일 후 마감"
                    reminders.append({
                        "type": "todo", "id": t["id"],
                        "title": t["title"],
                        "body": body,
                        "url": "/todos",
                        "time": t["due_date"] + "T09:00:00",
                        "notify_at": notify_at.isoformat(),
                    })

        # ─── Habits: remind at specified times ───
        habits = conn.execute(
            "SELECT id, name, icon, reminder_times, frequency_detail, target_count FROM habits "
            "WHERE profile_id=? AND archived=0 AND reminder_times IS NOT NULL AND reminder_times != '[]' AND reminder_times != ''",
            (pid,)
        ).fetchall()

        for h in habits:
            try:
                times = json.loads(h["reminder_times"]) if h["reminder_times"] else []
            except (json.JSONDecodeError, TypeError):
                times = []
            for t_str in times:
                try:
                    parts = t_str.split(":")
                    habit_dt = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
                except (ValueError, IndexError):
                    continue
                diff = (habit_dt - now).total_seconds()
                if -300 <= diff <= 300:
                    reminders.append({
                        "type": "habit", "id": h["id"],
                        "title": f"{h['icon']} {h['name']}",
                        "body": "습관 실천 시간입니다",
                        "url": "/habits",
                        "time": habit_dt.isoformat(),
                        "notify_at": habit_dt.isoformat(),
                    })

        # ─── D-days: remind N days before ───
        if dday_offsets:
            max_dday_days = max((o.get("value", 1) for o in dday_offsets if o.get("unit") == "day"), default=1)
            dday_lookahead = (date.today() + timedelta(days=max_dday_days + 1)).isoformat()
            ddays = conn.execute(
                "SELECT id, title, target_date, icon, reminder_offsets FROM ddays "
                "WHERE profile_id=? AND target_date >= ? AND target_date <= ?",
                (pid, today_str, dday_lookahead),
            ).fetchall()
            for dd in ddays:
                try:
                    target_dt = datetime.strptime(dd["target_date"], "%Y-%m-%d").replace(hour=9, minute=0)
                except (ValueError, TypeError):
                    continue
                item_offsets = _parse_offsets(dd["reminder_offsets"]) if dd["reminder_offsets"] else dday_offsets
                notify_times = _compute_notify_times(target_dt, item_offsets)
                for notify_at in notify_times:
                    diff = (notify_at - now).total_seconds()
                    if -300 <= diff <= 300:
                        days_left = (target_dt.date() - date.today()).days
                        body = f"D-{days_left}" if days_left > 0 else "D-Day"
                        reminders.append({
                            "type": "dday", "id": dd["id"],
                            "title": f"{dd['icon'] or ''} {dd['title']}",
                            "body": body,
                            "url": "/ddays",
                            "time": dd["target_date"] + "T09:00:00",
                            "notify_at": notify_at.isoformat(),
                        })

    return JSONResponse(reminders)
