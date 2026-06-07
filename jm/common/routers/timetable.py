"""Timetable router — /timetable, /timetable/blocks, presets, templates."""

import json
from datetime import date, timedelta, datetime

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from common.utils import clamp_text, fix_mojibake

router = APIRouter()

# Preset templates for timetable blocks
TIMETABLE_PRESETS = {
    "worker": {
        "label": "직장인",
        "blocks": [
            ("07:00", "09:00", "출근 준비", "#f59e0b", ""),
            ("09:00", "12:00", "업무", "#6366f1", ""),
            ("12:00", "13:00", "점심", "#10b981", ""),
            ("13:00", "18:00", "업무", "#6366f1", ""),
            ("18:00", "19:00", "퇴근", "#f59e0b", ""),
            ("19:00", "23:00", "자유시간", "#8b5cf6", ""),
        ],
    },
    "student": {
        "label": "학생",
        "blocks": [
            ("07:00", "08:00", "등교 준비", "#f59e0b", ""),
            ("08:00", "12:00", "수업", "#6366f1", ""),
            ("12:00", "13:00", "점심", "#10b981", ""),
            ("13:00", "16:00", "수업", "#6366f1", ""),
            ("16:00", "18:00", "자습", "#8b5cf6", ""),
            ("18:00", "19:00", "저녁", "#10b981", ""),
            ("19:00", "22:00", "공부", "#6366f1", ""),
        ],
    },
    "free": {
        "label": "자유",
        "blocks": [
            ("08:00", "23:00", "자유시간", "#8b5cf6", ""),
        ],
    },
}

# Day type labels for UI
DAY_TYPE_LABELS = {
    "today": "오늘",
    "default": "기본",
    "weekday": "평일",
    "weekend": "주말",
    "mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일",
}
DAY_TYPE_ORDER = ["today", "default", "weekday", "weekend", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_TO_DAY_TYPE = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


def resolve_timetable_blocks(conn, pid: int, target: date) -> list:
    """Resolve which timetable_blocks apply for a given date using day_type priority.
    Priority: specific date (YYYY-MM-DD) > weekday name (mon~sun) > weekday/weekend > default.
    """
    target_str = target.isoformat()
    weekday_num = target.weekday()
    day_type_name = WEEKDAY_TO_DAY_TYPE[weekday_num]
    is_weekend = weekday_num >= 5

    candidates = conn.execute("""
        SELECT * FROM timetable_blocks
        WHERE profile_id = ? AND day_type IN (?, ?, ?, 'default')
        ORDER BY sort_order, id
    """, (pid, target_str, day_type_name, "weekend" if is_weekend else "weekday")).fetchall()

    if not candidates:
        return []

    by_type = {}
    for row in candidates:
        dt = row["day_type"]
        by_type.setdefault(dt, []).append(dict(row))

    if target_str in by_type:
        return by_type[target_str]
    if day_type_name in by_type:
        return by_type[day_type_name]
    wk_type = "weekend" if is_weekend else "weekday"
    if wk_type in by_type:
        return by_type[wk_type]
    return by_type.get("default", [])


def has_any_blocks(conn, pid: int) -> bool:
    """Check if user has any timetable blocks at all."""
    row = conn.execute("SELECT COUNT(*) FROM timetable_blocks WHERE profile_id=?", (pid,)).fetchone()
    return row[0] > 0


@router.get("/timetable", response_class=HTMLResponse)
async def timetable_page(request: Request, dt: str = "", day_type: str = ""):
    S = request.app.state
    pid = S.get_profile_id(request)
    today = date.today()
    if dt:
        try:
            target = date.fromisoformat(dt)
        except ValueError:
            target = today
    else:
        target = today
    target_str = target.isoformat()
    weekday_names = ['월', '화', '수', '목', '금', '토', '일']
    weekday_label = weekday_names[target.weekday()]

    with S.get_db() as conn:
        events = conn.execute("""
            SELECT e.*, c.name as category_name
            FROM events e LEFT JOIN categories c ON e.category_id = c.id
            WHERE e.profile_id = ? AND date(e.start_time) = ?
            ORDER BY e.start_time ASC
        """, (pid, target_str)).fetchall()

        todos = conn.execute("""
            SELECT t.*, c.name as category_name, c.color as category_color
            FROM todos t LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.profile_id = ? AND t.due_date = ?
            ORDER BY t.priority ASC, t.sort_order ASC
        """, (pid, target_str)).fetchall()

        habits = conn.execute(
            "SELECT * FROM habits WHERE profile_id=? AND archived=0 ORDER BY sort_order", (pid,)
        ).fetchall()

        habit_logs_today = conn.execute(
            "SELECT habit_id, log_time FROM habit_logs WHERE profile_id=? AND log_date=?",
            (pid, target_str)
        ).fetchall()
        done_habit_ids = {r["habit_id"] for r in habit_logs_today}

        categories = conn.execute("SELECT * FROM categories ORDER BY sort_order").fetchall()

        user_blocks = resolve_timetable_blocks(conn, pid, target)
        _has_blocks = has_any_blocks(conn, pid)

        edit_day_type = day_type if day_type in DAY_TYPE_ORDER else ""
        if edit_day_type == "today":
            edit_blocks = user_blocks
        elif edit_day_type:
            edit_blocks = conn.execute(
                "SELECT * FROM timetable_blocks WHERE profile_id=? AND day_type=? ORDER BY sort_order, id",
                (pid, edit_day_type)
            ).fetchall()
            edit_blocks = [dict(b) for b in edit_blocks]
        else:
            edit_blocks = user_blocks

        existing_day_types = conn.execute(
            "SELECT DISTINCT day_type FROM timetable_blocks WHERE profile_id=?", (pid,)
        ).fetchall()
        existing_day_types = {r["day_type"] for r in existing_day_types}

    # Build time blocks for the circular chart
    inner_blocks = []
    for ev in events:
        ev = dict(ev)
        st = ev.get("start_time", "")
        et = ev.get("end_time", "")
        if not st or "T" not in st:
            continue
        try:
            sh, sm = int(st[11:13]), int(st[14:16])
            start_h = sh + sm / 60.0
        except (ValueError, IndexError):
            continue
        if et and "T" in et:
            try:
                eh, em = int(et[11:13]), int(et[14:16])
                end_h = eh + em / 60.0
            except (ValueError, IndexError):
                end_h = min(start_h + 1, 24)
        else:
            end_h = min(start_h + 1, 24)
        if end_h <= start_h:
            end_h = min(start_h + 1, 24) if end_h == 0 else min(start_h + 0.5, 24)
        inner_blocks.append({
            "type": "event",
            "title": ev["title"],
            "start_hour": start_h,
            "end_hour": end_h,
            "color": ev.get("color") or "#6366f1",
            "start_time": st,
            "end_time": et or "",
            "id": ev["id"],
        })

    for h in habits:
        hd = dict(h)
        try:
            fd = json.loads(hd["frequency_detail"]) if hd.get("frequency_detail") else None
        except (json.JSONDecodeError, TypeError):
            fd = None
        if not fd:
            continue
        if fd.get("type") == "specific_times":
            times = fd.get("times", [])
            for t in times:
                try:
                    parts = t.split(":")
                    th = int(parts[0]) + int(parts[1]) / 60.0
                except (ValueError, IndexError):
                    continue
                inner_blocks.append({
                    "type": "habit",
                    "title": f"{hd.get('icon', '')} {hd['name']}",
                    "start_hour": th,
                    "end_hour": min(th + 0.5, 24),
                    "color": hd.get("color") or "#10b981",
                    "id": hd["id"],
                    "done": hd["id"] in done_habit_ids,
                })
        elif fd.get("type") == "every_n_hours":
            interval = fd.get("interval", 2)
            if not isinstance(interval, (int, float)) or interval <= 0:
                interval = 2
            raw_start = fd.get("start", fd.get("start_hour", "08:00"))
            raw_end = fd.get("end", fd.get("end_hour", "22:00"))
            start = int(raw_start.split(":")[0]) + int(raw_start.split(":")[1]) / 60.0 if isinstance(raw_start, str) and ":" in raw_start else (raw_start if isinstance(raw_start, (int, float)) else 8)
            end = int(raw_end.split(":")[0]) + int(raw_end.split(":")[1]) / 60.0 if isinstance(raw_end, str) and ":" in raw_end else (raw_end if isinstance(raw_end, (int, float)) else 22)
            hour = start
            while hour < end:
                inner_blocks.append({
                    "type": "habit",
                    "title": f"{hd.get('icon', '')} {hd['name']}",
                    "start_hour": hour,
                    "end_hour": min(hour + 0.5, 24),
                    "color": hd.get("color") or "#10b981",
                    "id": hd["id"],
                    "done": hd["id"] in done_habit_ids,
                })
                hour += interval

    inner_blocks.sort(key=lambda b: b["start_hour"])

    display_blocks = edit_blocks if edit_day_type else user_blocks
    outer_blocks = []
    for ub in display_blocks:
        try:
            sp = ub["start_time"].split(":")
            ep = ub["end_time"].split(":")
            start_h = int(sp[0]) + int(sp[1]) / 60.0
            end_h = int(ep[0]) + int(ep[1]) / 60.0
        except (ValueError, IndexError, KeyError):
            continue
        start_h = min(start_h, 24.0)
        end_h = min(end_h, 24.0)
        if end_h <= start_h:
            end_h = 24.0
        outer_blocks.append({
            "type": "user_block",
            "title": f"{ub.get('icon', '')} {ub['title']}".strip(),
            "start_hour": start_h,
            "end_hour": end_h,
            "color": ub.get("color") or "#6366f1",
            "id": ub["id"],
            "raw_start": ub["start_time"],
            "raw_end": ub["end_time"],
        })
    outer_blocks.sort(key=lambda b: b["start_hour"])

    time_blocks = outer_blocks + inner_blocks

    schedule_list = []
    for ev in events:
        ev = dict(ev)
        st = ev.get("start_time", "")
        et = ev.get("end_time", "")
        schedule_list.append({
            "type": "event",
            "title": ev["title"],
            "time_label": (st[11:16] if st and "T" in st else "종일") + (" ~ " + et[11:16] if et and "T" in et else ""),
            "color": ev.get("color") or "#6366f1",
            "id": ev["id"],
        })

    prev_date = (target - timedelta(days=1)).isoformat()
    next_date = (target + timedelta(days=1)).isoformat()

    color_presets = ["#ef4444", "#f59e0b", "#10b981", "#6366f1", "#8b5cf6", "#ec4899", "#0ea5e9", "#64748b"]
    icon_presets = ["", "📚", "💼", "🏃", "🍽️", "😴", "🎮", "🎵", "✏️", "🧘"]

    return S.render(request, "timetable.html", {
        "page": "timetable",
        "target_date": target_str,
        "target_weekday": weekday_label,
        "target_day": target.day,
        "target_month": target.month,
        "is_today": target == today,
        "time_blocks": time_blocks,
        "inner_blocks": inner_blocks,
        "outer_blocks": outer_blocks,
        "schedule_list": schedule_list,
        "todos": [dict(t) for t in todos],
        "prev_date": prev_date,
        "next_date": next_date,
        "categories": [dict(c) for c in categories],
        "user_blocks": [dict(b) if not isinstance(b, dict) else b for b in edit_blocks],
        "has_blocks": _has_blocks,
        "presets": TIMETABLE_PRESETS,
        "color_presets": color_presets,
        "icon_presets": icon_presets,
        "day_type_labels": DAY_TYPE_LABELS,
        "day_type_order": DAY_TYPE_ORDER,
        "edit_day_type": edit_day_type or "default",
        "existing_day_types": existing_day_types,
    })


@router.get("/timetable/blocks", response_class=HTMLResponse)
async def timetable_blocks_list(request: Request, day_type: str = "default"):
    """Return block list partial for HTMX."""
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        blocks = conn.execute(
            "SELECT * FROM timetable_blocks WHERE profile_id=? AND day_type=? ORDER BY sort_order, start_time",
            (pid, day_type)
        ).fetchall()
    blocks = [dict(b) for b in blocks]
    color_presets = ["#ef4444", "#f59e0b", "#10b981", "#6366f1", "#8b5cf6", "#ec4899", "#0ea5e9", "#64748b"]
    icon_presets = ["", "📚", "💼", "🏃", "🍽️", "😴", "🎮", "🎵", "✏️", "🧘"]
    return S.render(request, "partials/timetable_block_list.html", {
        "user_blocks": blocks,
        "edit_day_type": day_type,
        "color_presets": color_presets,
        "icon_presets": icon_presets,
    })


@router.post("/timetable/blocks", response_class=HTMLResponse)
async def create_timetable_block(request: Request,
                                  start_time: str = Form(""),
                                  end_time: str = Form(""),
                                  title: str = Form(""),
                                  color: str = Form("#6366f1"),
                                  icon: str = Form(""),
                                  day_type: str = Form("default")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 50).strip()
    if not title or not start_time or not end_time:
        return S.redirect(request, "/timetable")
    import re
    time_re = re.compile(r'^\d{2}:\d{2}$')
    if not time_re.match(start_time) or not time_re.match(end_time):
        return S.redirect(request, "/timetable")
    if start_time > "24:00" or end_time > "24:00":
        return S.redirect(request, "/timetable")
    if end_time <= start_time:
        return S.redirect(request, "/timetable")
    if day_type not in DAY_TYPE_ORDER:
        day_type = "default"
    with S.get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM timetable_blocks WHERE profile_id=? AND day_type=?",
            (pid, day_type)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO timetable_blocks (profile_id, day_type, start_time, end_time, title, color, icon, sort_order) VALUES (?,?,?,?,?,?,?,?)",
            (pid, day_type, start_time, end_time, title, color, icon or "", max_order + 1)
        )
    if request.headers.get("HX-Request"):
        return S.redirect(request, f"/timetable?day_type={day_type}")
    return S.redirect(request, "/timetable")


@router.put("/timetable/blocks/{block_id}", response_class=HTMLResponse)
async def update_timetable_block(request: Request, block_id: int,
                                  start_time: str = Form(""),
                                  end_time: str = Form(""),
                                  title: str = Form(""),
                                  color: str = Form("#6366f1"),
                                  icon: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 50).strip()
    if not title or not start_time or not end_time:
        return S.redirect(request, "/timetable")
    import re
    time_re = re.compile(r'^\d{2}:\d{2}$')
    if not time_re.match(start_time) or not time_re.match(end_time):
        return S.redirect(request, "/timetable")
    if start_time > "24:00" or end_time > "24:00":
        return S.redirect(request, "/timetable")
    if end_time <= start_time:
        return S.redirect(request, "/timetable")
    with S.get_db() as conn:
        conn.execute("""
            UPDATE timetable_blocks SET start_time=?, end_time=?, title=?, color=?, icon=?
            WHERE id=? AND profile_id=?
        """, (start_time, end_time, title, color, icon or "", block_id, pid))
    return S.redirect(request, "/timetable")


@router.delete("/timetable/blocks/{block_id}", response_class=HTMLResponse)
async def delete_timetable_block(request: Request, block_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM timetable_blocks WHERE id=? AND profile_id=?", (block_id, pid))
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return S.redirect(request, "/timetable")


@router.post("/timetable/templates/copy", response_class=HTMLResponse)
async def copy_timetable_template(request: Request,
                                   from_type: str = Form("default"),
                                   to_type: str = Form("")):
    """Copy blocks from one day_type to another."""
    S = request.app.state
    pid = S.get_profile_id(request)
    if not to_type or to_type not in DAY_TYPE_ORDER or from_type not in DAY_TYPE_ORDER:
        return S.redirect(request, "/timetable")
    with S.get_db() as conn:
        conn.execute("DELETE FROM timetable_blocks WHERE profile_id=? AND day_type=?", (pid, to_type))
        source = conn.execute(
            "SELECT start_time, end_time, title, color, icon, sort_order FROM timetable_blocks WHERE profile_id=? AND day_type=? ORDER BY sort_order",
            (pid, from_type)
        ).fetchall()
        if source:
            for row in source:
                conn.execute(
                    "INSERT INTO timetable_blocks (profile_id, day_type, start_time, end_time, title, color, icon, sort_order) VALUES (?,?,?,?,?,?,?,?)",
                    (pid, to_type, row["start_time"], row["end_time"], row["title"], row["color"], row["icon"], row["sort_order"])
                )
    return S.redirect(request, f"/timetable?day_type={to_type}")


@router.post("/timetable/presets/apply", response_class=HTMLResponse)
async def apply_timetable_preset(request: Request, preset: str = Form("")):
    """Apply a preset template (worker, student, free)."""
    S = request.app.state
    pid = S.get_profile_id(request)
    if preset not in TIMETABLE_PRESETS:
        return S.redirect(request, "/timetable")
    blocks = TIMETABLE_PRESETS[preset]["blocks"]
    with S.get_db() as conn:
        conn.execute("DELETE FROM timetable_blocks WHERE profile_id=? AND day_type='default'", (pid,))
        for i, (st, et, title, color, icon) in enumerate(blocks):
            conn.execute(
                "INSERT INTO timetable_blocks (profile_id, day_type, start_time, end_time, title, color, icon, sort_order) VALUES (?,?,?,?,?,?,?,?)",
                (pid, "default", st, et, title, color, icon, i)
            )
    return S.redirect(request, "/timetable")
