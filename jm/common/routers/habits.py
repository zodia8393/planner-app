"""Habits CRUD router — /habits, /habits/{id}/toggle, increment, decrement."""

import json
from datetime import date, timedelta, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from common.utils import clamp_text, fix_mojibake, safe_int

router = APIRouter()


@router.get("/habits", response_class=HTMLResponse)
async def habits_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    today = date.today()
    today_str = today.isoformat()
    with S.get_db() as conn:
        habits = conn.execute(
            "SELECT * FROM habits WHERE profile_id=? AND archived=0 ORDER BY sort_order", (pid,)
        ).fetchall()
        start_date = (today - timedelta(days=29)).isoformat()
        logs = conn.execute(
            "SELECT habit_id, log_date, log_time, count FROM habit_logs WHERE profile_id=? AND log_date>=?",
            (pid, start_date),
        ).fetchall()
        today_logs = conn.execute(
            "SELECT habit_id, log_time, count FROM habit_logs WHERE profile_id=? AND log_date=?",
            (pid, today_str),
        ).fetchall()
        week_start = (today - timedelta(days=today.weekday())).isoformat()
        week_logs = conn.execute(
            "SELECT habit_id, log_date FROM habit_logs WHERE profile_id=? AND log_date>=? AND log_date<=?",
            (pid, week_start, today_str),
        ).fetchall()
    logs_set = {(r["habit_id"], r["log_date"]) for r in logs}
    today_counts = {}
    today_time_checks = {}
    for r in today_logs:
        hid = r["habit_id"]
        today_counts[hid] = today_counts.get(hid, 0) + (r["count"] or 1)
        if r["log_time"]:
            today_time_checks.setdefault(hid, set()).add(r["log_time"])
    week_counts = {}
    for r in week_logs:
        hid = r["habit_id"]
        week_counts[hid] = week_counts.get(hid, 0) + 1

    habits_data = []
    for h in habits:
        hd = dict(h)
        hd["frequency_detail_parsed"] = json.loads(hd["frequency_detail"]) if hd.get("frequency_detail") else None
        hd["target_count"] = hd.get("target_count") or 1

        fd = hd["frequency_detail_parsed"]
        if fd:
            hd["tracking_type"] = fd.get("type", "daily")
        else:
            hd["tracking_type"] = "daily"

        hd["today_count"] = today_counts.get(hd["id"], 0)
        hd["today_time_checks"] = today_time_checks.get(hd["id"], set())
        hd["week_count"] = week_counts.get(hd["id"], 0)

        streak = 0
        d = today
        while True:
            if (hd["id"], d.isoformat()) in logs_set:
                streak += 1
                d -= timedelta(days=1)
            else:
                break
        hd["streak"] = streak

        if hd["tracking_type"] == "times_per_day":
            hd["today_done"] = hd["today_count"] >= hd["target_count"]
        elif hd["tracking_type"] == "specific_times":
            times = fd.get("times", []) if fd else []
            hd["today_done"] = len(hd["today_time_checks"]) >= len(times)
            hd["specific_times"] = times
        elif hd["tracking_type"] == "every_n_hours":
            hd["today_done"] = hd["today_count"] >= hd["target_count"]
        elif hd["tracking_type"] == "times_per_week":
            weekly_target = fd.get("count", 3) if fd else 3
            hd["today_done"] = hd["week_count"] >= weekly_target
            hd["weekly_target"] = weekly_target
        else:
            hd["today_done"] = (hd["id"], today_str) in logs_set

        habits_data.append(hd)
    dates = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    return S.render(request, "habits.html", {
        "page": "habits", "habits": habits_data,
        "logs_set": logs_set, "dates": dates, "today_str": today_str,
    })


@router.post("/habits", response_class=HTMLResponse)
async def create_habit(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    form = await request.form()
    name = clamp_text(fix_mojibake(form.get("name", "")), 50).strip()
    if not name:
        return S.redirect(request, "/habits")
    icon = form.get("icon", "✅") or "✅"
    color = form.get("color", "#6366f1")
    tracking_type = form.get("tracking_type", "daily")
    if tracking_type not in ("daily", "counter", "interval", "specific", "weekly"):
        tracking_type = "daily"
    target_count = safe_int(form.get("target_count", "1"), 1)
    reminder_enabled = form.get("reminder_enabled", "")

    frequency_detail = None
    reminder_times = None

    if tracking_type == "counter":
        frequency_detail = json.dumps({"type": "times_per_day", "count": target_count})
    elif tracking_type == "interval":
        interval_hours = safe_int(form.get("interval_hours", "2"), 2)
        start_time = form.get("interval_start", "08:00") or "08:00"
        end_time = form.get("interval_end", "22:00") or "22:00"
        frequency_detail = json.dumps({"type": "every_n_hours", "interval": interval_hours, "start": start_time, "end": end_time})
        if reminder_enabled:
            times = []
            sh, sm = int(start_time.split(":")[0]), int(start_time.split(":")[1])
            eh = int(end_time.split(":")[0])
            current_h, current_m = sh, sm
            while current_h < eh or (current_h == eh and current_m == 0):
                times.append(f"{current_h:02d}:{current_m:02d}")
                current_h += interval_hours
            reminder_times = json.dumps(times)
    elif tracking_type == "specific":
        times_raw = form.getlist("specific_times")
        times = [t for t in times_raw if t]
        if times:
            frequency_detail = json.dumps({"type": "specific_times", "times": times})
            target_count = len(times)
            if reminder_enabled:
                reminder_times = json.dumps(times)
    elif tracking_type == "weekly":
        weekly_count = safe_int(form.get("weekly_count", "3"), 3)
        frequency_detail = json.dumps({"type": "times_per_week", "count": weekly_count})
        target_count = weekly_count
    else:
        target_count = 1
        if reminder_enabled:
            rt = form.get("reminder_time", "")
            if rt:
                reminder_times = json.dumps([rt])

    with S.get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM habits WHERE profile_id=?", (pid,)).fetchone()[0]
        conn.execute(
            "INSERT INTO habits (profile_id, name, icon, color, sort_order, target_count, frequency_detail, reminder_times) VALUES (?,?,?,?,?,?,?,?)",
            (pid, name, icon, color, max_order + 1, target_count, frequency_detail, reminder_times),
        )
    return S.redirect(request, "/habits")


@router.post("/habits/{habit_id}/toggle", response_class=HTMLResponse)
async def toggle_habit(request: Request, habit_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    form = await request.form()
    log_date = form.get("date", "") or date.today().isoformat()
    log_time = form.get("log_time", "") or None
    action = form.get("action", "toggle")

    with S.get_db() as conn:
        habit = conn.execute("SELECT * FROM habits WHERE id=? AND profile_id=?", (habit_id, pid)).fetchone()
        if not habit:
            return S.redirect(request, "/habits")

        fd = json.loads(habit["frequency_detail"]) if habit["frequency_detail"] else None
        tracking_type = fd.get("type", "daily") if fd else "daily"

        if tracking_type in ("times_per_day", "every_n_hours") and action in ("increment", "toggle"):
            counter_time = datetime.now().strftime("%H:%M:%S")
            if action == "toggle":
                count_today = conn.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM habit_logs WHERE habit_id=? AND log_date=?",
                    (habit_id, log_date)
                ).fetchone()[0]
                target = habit["target_count"] or 1
                if count_today >= target:
                    last = conn.execute(
                        "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? ORDER BY id DESC LIMIT 1",
                        (habit_id, log_date)
                    ).fetchone()
                    if last:
                        conn.execute("DELETE FROM habit_logs WHERE id=?", (last["id"],))
                else:
                    conn.execute(
                        "INSERT INTO habit_logs (habit_id, profile_id, log_date, log_time, count) VALUES (?,?,?,?,1)",
                        (habit_id, pid, log_date, counter_time),
                    )
            elif action == "increment":
                conn.execute(
                    "INSERT INTO habit_logs (habit_id, profile_id, log_date, log_time, count) VALUES (?,?,?,?,1)",
                    (habit_id, pid, log_date, counter_time),
                )
        elif tracking_type == "specific_times" and log_time:
            existing = conn.execute(
                "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? AND log_time=?",
                (habit_id, log_date, log_time)
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM habit_logs WHERE id=?", (existing["id"],))
            else:
                conn.execute(
                    "INSERT INTO habit_logs (habit_id, profile_id, log_date, log_time, count) VALUES (?,?,?,?,1)",
                    (habit_id, pid, log_date, log_time),
                )
        elif action == "decrement":
            last = conn.execute(
                "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? ORDER BY id DESC LIMIT 1",
                (habit_id, log_date)
            ).fetchone()
            if last:
                conn.execute("DELETE FROM habit_logs WHERE id=?", (last["id"],))
        else:
            existing = conn.execute(
                "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? AND log_time IS NULL",
                (habit_id, log_date)
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM habit_logs WHERE id=?", (existing["id"],))
            else:
                conn.execute(
                    "INSERT INTO habit_logs (habit_id, profile_id, log_date, count) VALUES (?,?,?,1)",
                    (habit_id, pid, log_date),
                )
    return S.redirect(request, "/habits")


@router.post("/habits/{habit_id}/increment", response_class=HTMLResponse)
async def increment_habit(request: Request, habit_id: int):
    """Quick increment for counter-type habits (HTMX)."""
    S = request.app.state
    pid = S.get_profile_id(request)
    log_date = date.today().isoformat()
    log_time = datetime.now().strftime("%H:%M:%S")
    with S.get_db() as conn:
        conn.execute(
            "INSERT INTO habit_logs (habit_id, profile_id, log_date, log_time, count) VALUES (?,?,?,?,1)",
            (habit_id, pid, log_date, log_time),
        )
    return S.redirect(request, "/habits")


@router.post("/habits/{habit_id}/decrement", response_class=HTMLResponse)
async def decrement_habit(request: Request, habit_id: int):
    """Quick decrement for counter-type habits (HTMX)."""
    S = request.app.state
    pid = S.get_profile_id(request)
    log_date = date.today().isoformat()
    with S.get_db() as conn:
        last = conn.execute(
            "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? ORDER BY id DESC LIMIT 1",
            (habit_id, log_date)
        ).fetchone()
        if last:
            conn.execute("DELETE FROM habit_logs WHERE id=?", (last["id"],))
    return S.redirect(request, "/habits")


@router.delete("/habits/{habit_id}", response_class=HTMLResponse)
async def delete_habit(request: Request, habit_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM habits WHERE id=? AND profile_id=?", (habit_id, pid))
    return HTMLResponse("")
