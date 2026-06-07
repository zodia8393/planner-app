"""Today view router — /today unified daily overview."""

import json
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from common.constants import PRIORITY_MAP

router = APIRouter()


@router.get("/today", response_class=HTMLResponse)
async def today_view(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    today = date.today()
    today_str = today.isoformat()
    with S.get_db() as conn:
        todos = conn.execute("""
            SELECT t.*, c.name as category_name, c.color as category_color
            FROM todos t LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.profile_id=? AND ((t.due_date<=? AND t.completed=0) OR (t.completed=1 AND date(t.completed_at)=?))
            ORDER BY t.completed ASC, t.priority ASC, t.sort_order ASC
        """, (pid, today_str, today_str)).fetchall()
        events = conn.execute("""
            SELECT e.*, c.name as category_name
            FROM events e LEFT JOIN categories c ON e.category_id = c.id
            WHERE e.profile_id=? AND date(e.start_time)=?
            ORDER BY e.start_time ASC
        """, (pid, today_str)).fetchall()
        worklogs = conn.execute("""
            SELECT w.*, c.name as category_name, c.color as category_color
            FROM work_logs w LEFT JOIN categories c ON w.category_id = c.id
            WHERE w.profile_id=? AND w.log_date=?
            ORDER BY w.created_at DESC
        """, (pid, today_str)).fetchall()
        habits = conn.execute("SELECT * FROM habits WHERE profile_id=? AND archived=0 ORDER BY sort_order", (pid,)).fetchall()
        habit_logs_today = conn.execute(
            "SELECT habit_id, count FROM habit_logs WHERE profile_id=? AND log_date=?", (pid, today_str)
        ).fetchall()
    done_habits = {r["habit_id"] for r in habit_logs_today}
    today_habit_counts: dict = {}
    for r in habit_logs_today:
        hid = r["habit_id"]
        today_habit_counts[hid] = today_habit_counts.get(hid, 0) + (r["count"] or 1)
    habits_data = []
    for h in habits:
        hd = dict(h)
        fd = json.loads(hd["frequency_detail"]) if hd.get("frequency_detail") else None
        tracking_type = fd.get("type", "daily") if fd else "daily"
        if tracking_type in ("times_per_day", "every_n_hours"):
            target = hd.get("target_count") or 1
            hd["today_done"] = today_habit_counts.get(hd["id"], 0) >= target
        else:
            hd["today_done"] = hd["id"] in done_habits
        habits_data.append(hd)
    return S.render(request, "today.html", {
        "page": "today", "today_str": today_str,
        "todos": [dict(r) for r in todos],
        "events": [dict(r) for r in events],
        "worklogs": [dict(r) for r in worklogs],
        "habits": habits_data,
        "priority_map": PRIORITY_MAP,
    })
