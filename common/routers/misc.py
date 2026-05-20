import json
from datetime import date, timedelta, datetime
from typing import Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response
from common.constants import RRULE_FREQ_OPTIONS, RRULE_DAY_OPTIONS
from common.nlp_date import parse_korean_date, extract_date_from_text, format_date_display
from common.recurrence import build_rrule, parse_rrule, rrule_to_korean
from common.utils import clamp_text, fix_mojibake, validate_date_str
from common.search import search_fts

router = APIRouter()


# ── Todo Templates ──

@router.get("/todo-templates", response_class=HTMLResponse)
async def todo_templates_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        tpls = [dict(r) for r in conn.execute(
            "SELECT * FROM todo_templates WHERE profile_id=? ORDER BY created_at DESC", (pid,)
        ).fetchall()]
        categories = [dict(r) for r in S.get_categories(conn, pid)]
    for t in tpls:
        t["items"] = json.loads(t["items_json"])
    return S.render(request, "todo_templates.html", {
        "page": "todo-templates", "templates": tpls, "categories": categories,
    })


@router.post("/todo-templates", response_class=HTMLResponse)
async def create_todo_template(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    form = await request.form()
    name = clamp_text(fix_mojibake(form.get("name", "")), 100)
    items_json = form.get("items_json", "[]")
    if not name:
        return S.redirect(request, "/todo-templates")
    with S.get_db() as conn:
        conn.execute(
            "INSERT INTO todo_templates (profile_id, name, items_json) VALUES (?,?,?)",
            (pid, name, items_json))
    return S.redirect(request, "/todo-templates")


@router.post("/todo-templates/{tpl_id}/apply", response_class=HTMLResponse)
async def apply_todo_template(request: Request, tpl_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        tpl = conn.execute("SELECT * FROM todo_templates WHERE id=? AND profile_id=?", (tpl_id, pid)).fetchone()
        if not tpl:
            return S.redirect(request, "/todo-templates")
        items = json.loads(tpl["items_json"])
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
        today = date.today().isoformat()
        for i, item in enumerate(items):
            conn.execute(
                "INSERT INTO todos (profile_id, title, description, priority, category_id, due_date, tags, sort_order) VALUES (?,?,?,?,?,?,?,?)",
                (pid, item.get("title", ""), item.get("description", ""), item.get("priority", 2),
                 item.get("category_id") or None, today, item.get("tags", ""), max_order + i + 1))
    return S.redirect(request, "/todos")


@router.delete("/todo-templates/{tpl_id}", response_class=HTMLResponse)
async def delete_todo_template(request: Request, tpl_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM todo_templates WHERE id=? AND profile_id=?", (tpl_id, pid))
    return S.redirect(request, "/todo-templates")


@router.post("/todo-templates/from-todos", response_class=HTMLResponse)
async def create_template_from_todos(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    form = await request.form()
    name = clamp_text(fix_mojibake(form.get("name", "")), 100)
    todo_ids = form.getlist("todo_ids")
    if not name or not todo_ids:
        return S.redirect(request, "/todos")
    placeholders = ",".join("?" * len(todo_ids))
    with S.get_db() as conn:
        todos = conn.execute(
            f"SELECT title, description, priority, category_id, tags FROM todos WHERE id IN ({placeholders}) AND profile_id=?",
            (*[int(i) for i in todo_ids], pid)).fetchall()
        items = [{"title": t["title"], "description": t["description"] or "", "priority": t["priority"],
                  "category_id": t["category_id"], "tags": t["tags"] or ""} for t in todos]
        conn.execute("INSERT INTO todo_templates (profile_id, name, items_json) VALUES (?,?,?)",
                     (pid, name, json.dumps(items, ensure_ascii=False)))
    return S.redirect(request, "/todo-templates")


# ── Automation Rules ──

@router.get("/automations", response_class=HTMLResponse)
async def automations_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        rules = [dict(r) for r in conn.execute(
            "SELECT * FROM automation_rules WHERE profile_id=? ORDER BY created_at DESC", (pid,)
        ).fetchall()]
        categories = [dict(r) for r in S.get_categories(conn, pid)]
    for ru in rules:
        ru["_tc"] = json.loads(ru.get("trigger_config") or "{}")
        ru["_ac"] = json.loads(ru.get("action_config") or "{}")
        # Generate human-readable description for RRULE triggers
        if ru["trigger_type"] == "rrule":
            ru["_trigger_desc"] = rrule_to_korean(ru["_tc"].get("rrule", ""))
        else:
            ru["_trigger_desc"] = ""
    return S.render(request, "automations.html", {
        "page": "automations", "rules": rules, "categories": categories,
        "rrule_freq_options": RRULE_FREQ_OPTIONS,
        "rrule_day_options": RRULE_DAY_OPTIONS,
        "rrule_to_korean": rrule_to_korean,
    })


@router.post("/automations", response_class=HTMLResponse)
async def create_automation(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    form = await request.form()
    name = clamp_text(fix_mojibake(form.get("name", "")), 100)
    if not name:
        return S.redirect(request, "/automations")
    trigger_type = form.get("trigger_type", "weekly")
    trigger_config = form.get("trigger_config", "{}")
    action_config = form.get("action_config", "{}")
    with S.get_db() as conn:
        conn.execute(
            "INSERT INTO automation_rules (profile_id, name, trigger_type, trigger_config, action_type, action_config) VALUES (?,?,?,?,?,?)",
            (pid, name, trigger_type, trigger_config, "create_todo", action_config))
    return S.redirect(request, "/automations")


@router.post("/automations/{rule_id}/toggle", response_class=HTMLResponse)
async def toggle_automation(request: Request, rule_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute(
            "UPDATE automation_rules SET enabled = CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=? AND profile_id=?",
            (rule_id, pid))
    return S.redirect(request, "/automations")


@router.delete("/automations/{rule_id}", response_class=HTMLResponse)
async def delete_automation(request: Request, rule_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM automation_rules WHERE id=? AND profile_id=?", (rule_id, pid))
    return S.redirect(request, "/automations")


# ── Audit Log ──

@router.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(request: Request, entity_type: str = "", limit: int = 50):
    S = request.app.state
    with S.get_db() as conn:
        if entity_type:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE entity_type=? ORDER BY created_at DESC LIMIT ?",
                (entity_type, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
    logs = []
    for r in rows:
        d = dict(r)
        d["changes"] = json.loads(d.get("changes_json") or "{}")
        logs.append(d)
    return S.render(request, "audit_log.html", {
        "page": "audit-log", "logs": logs, "entity_type": entity_type,
    })


# ── Review ──

@router.get("/review", response_class=HTMLResponse)
async def review_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    period = request.query_params.get("period", "week")
    offset = int(request.query_params.get("offset", "0"))
    today = date.today()

    if period == "month":
        first = today.replace(day=1)
        for _ in range(abs(offset)):
            first = (first - timedelta(days=1)).replace(day=1)
        if first.month == 12:
            last = first.replace(year=first.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            last = first.replace(month=first.month + 1, day=1) - timedelta(days=1)
        label = first.strftime("%Y년 %m월")
    else:
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        sunday = monday + timedelta(days=6)
        first, last = monday, sunday
        label = f"{first.strftime('%m/%d')} ~ {last.strftime('%m/%d')}"

    start_str = first.isoformat()
    end_str = last.isoformat()
    next_day = (last + timedelta(days=1)).isoformat()

    with S.get_db() as conn:
        total_todos = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE profile_id=? AND created_at>=? AND created_at<?",
            (pid, start_str, next_day)).fetchone()[0]
        completed_todos = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=1 AND completed_at>=? AND completed_at<?",
            (pid, start_str, next_day)).fetchone()[0]
        cat_stats = conn.execute(
            "SELECT c.name, c.color, COUNT(*) as total, "
            "SUM(CASE WHEN t.completed=1 THEN 1 ELSE 0 END) as done "
            "FROM todos t LEFT JOIN categories c ON t.category_id=c.id "
            "WHERE t.profile_id=? AND t.due_date>=? AND t.due_date<=? "
            "GROUP BY t.category_id ORDER BY total DESC",
            (pid, start_str, end_str)).fetchall()
        hours_data = conn.execute(
            "SELECT COALESCE(SUM(hours),0) as total_hours, COUNT(*) as log_count "
            "FROM work_logs WHERE profile_id=? AND log_date>=? AND log_date<=?",
            (pid, start_str, end_str)).fetchone()
        hours_by_cat = conn.execute(
            "SELECT c.name, c.color, SUM(w.hours) as hours "
            "FROM work_logs w LEFT JOIN categories c ON w.category_id=c.id "
            "WHERE w.profile_id=? AND w.log_date>=? AND w.log_date<=? "
            "GROUP BY w.category_id ORDER BY hours DESC",
            (pid, start_str, end_str)).fetchall()
        daily_completed = conn.execute(
            "SELECT date(completed_at) as d, COUNT(*) as cnt "
            "FROM todos WHERE profile_id=? AND completed=1 AND completed_at>=? AND completed_at<? "
            "GROUP BY date(completed_at) ORDER BY d",
            (pid, start_str, next_day)).fetchall()
        completion_rate = round(completed_todos / total_todos * 100) if total_todos > 0 else 0

    return S.render(request, "review.html", {
        "page": "review", "period": period, "offset": offset, "label": label,
        "total_todos": total_todos, "completed_todos": completed_todos,
        "completion_rate": completion_rate,
        "cat_stats": [dict(r) for r in cat_stats],
        "total_hours": round(hours_data["total_hours"], 1),
        "log_count": hours_data["log_count"],
        "hours_by_cat": [dict(r) for r in hours_by_cat],
        "daily_completed": [dict(r) for r in daily_completed],
        "start_str": start_str, "end_str": end_str,
    })


@router.get("/plans", response_class=HTMLResponse)
async def plans_redirect(request: Request, view: str = "week", offset: int = 0):
    S = request.app.state
    return S.redirect(request, f"/?plan_view={view}&plan_offset={offset}")


@router.post("/quick-todo", response_class=HTMLResponse)
async def quick_add_todo(request: Request,
                         title: str = Form(...),
                         due_date: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    due_date = validate_date_str(due_date)
    # NLP date extraction: if no explicit due_date, try parsing from title
    if not due_date:
        nlp_date, remaining_title = extract_date_from_text(title)
        if nlp_date and remaining_title:
            due_date = nlp_date.isoformat()
            title = remaining_title
    due_date = due_date or date.today().isoformat()
    with S.get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
        conn.execute("""
            INSERT INTO todos (title, due_date, sort_order, profile_id) VALUES (?, ?, ?, ?)
        """, (title, due_date, max_order + 1, pid))
    return S.redirect(request, "/")


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = ""):
    S = request.app.state
    pid = S.get_profile_id(request)
    results: dict = {"todos": [], "events": [], "memos": [], "notices": [], "worklogs": [], "entries": []}
    if q and len(q) >= 2:
        with S.get_db() as conn:
            results = search_fts(conn, q, pid, limit=50)

    total = sum(len(v) for v in results.values())
    return S.render(request, "search.html", {"page": "search", "q": q, "results": results, "total": total})


@router.post("/focus/complete", response_class=HTMLResponse)
async def focus_complete(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    body = await request.json()
    minutes = max(1, min(480, int(body.get("minutes", 25))))
    hours = round(minutes / 60, 2)
    cat_id = body.get("category_id") or None
    title = clamp_text(body.get("title", ""), 200) or f"집중 모드 {minutes}분"
    today_str = date.today().isoformat()
    with S.get_db() as conn:
        dup = conn.execute(
            "SELECT id FROM work_logs WHERE profile_id=? AND log_date=? AND title=? AND hours=? ORDER BY id DESC LIMIT 1",
            (pid, today_str, title, hours)).fetchone()
        if dup:
            return JSONResponse({"ok": True, "hours": hours})
        conn.execute(
            "INSERT INTO work_logs (profile_id, log_date, title, content, hours, category_id) VALUES (?,?,?,?,?,?)",
            (pid, today_str, title, f"집중 모드 {minutes}분 완료", hours, cat_id))
    return JSONResponse({"ok": True, "hours": hours})


@router.get("/api/reminders")
async def get_reminders(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    now = datetime.now()
    today_str = date.today().isoformat()
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
    reminders = []
    with S.get_db() as conn:
        # Overdue todos
        overdue = conn.execute(
            "SELECT id, title, due_date FROM todos WHERE profile_id=? AND completed=0 AND due_date < ? AND due_date IS NOT NULL AND due_date != '' ORDER BY due_date LIMIT 10",
            (pid, today_str),
        ).fetchall()
        for t in overdue:
            reminders.append({
                "type": "overdue", "id": t["id"], "title": t["title"],
                "body": f"마감일: {t['due_date']}", "url": "/todos?filter=overdue",
                "time": t["due_date"] + "T09:00:00",
            })
        # Today's todos
        today_todos = conn.execute(
            "SELECT id, title FROM todos WHERE profile_id=? AND completed=0 AND due_date=? ORDER BY priority, sort_order LIMIT 10",
            (pid, today_str),
        ).fetchall()
        for t in today_todos:
            reminders.append({
                "type": "today", "id": t["id"], "title": t["title"],
                "body": "오늘 마감", "url": "/todos",
                "time": today_str + "T09:00:00",
            })
        # Upcoming events within next 24 hours
        now_str = now.strftime("%Y-%m-%d %H:%M")
        tomorrow_dt_str = (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        upcoming_events = conn.execute(
            "SELECT id, title, start_time, memo FROM events "
            "WHERE profile_id=? AND start_time >= ? AND start_time <= ? "
            "ORDER BY start_time LIMIT 10",
            (pid, now_str, tomorrow_dt_str),
        ).fetchall()
        for ev in upcoming_events:
            st = ev["start_time"] or ""
            display_time = st[11:16] if len(st) >= 16 else st[:10]
            reminders.append({
                "type": "event", "id": ev["id"], "title": ev["title"],
                "body": f"시작: {display_time}", "url": "/calendar",
                "time": st if "T" in st else st.replace(" ", "T"),
            })
    return JSONResponse(reminders)


@router.get("/sw.js")
async def service_worker(request: Request):
    S = request.app.state
    sw_path = S.base_dir / "static" / "sw.js"
    if sw_path.exists():
        return Response(
            content=sw_path.read_text(),
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )
    # Minimal no-op service worker
    return Response(
        content="// No-op service worker\nself.addEventListener('fetch', () => {});",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@router.get("/api/parse-date")
async def parse_date_api(request: Request, text: str = ""):
    """Parse Korean natural language date text and return the result as JSON."""
    if not text.strip():
        return JSONResponse({"ok": False})
    parsed = parse_korean_date(text.strip())
    if parsed is None:
        return JSONResponse({"ok": False})
    return JSONResponse({
        "ok": True,
        "date": parsed.isoformat(),
        "display": format_date_display(parsed),
    })


@router.get("/api/widgets/today")
async def widget_today_data(request: Request):
    """Return JSON data for dashboard widgets (HTMX lazy loading)."""
    S = request.app.state
    pid = S.get_profile_id(request)
    today_str = date.today().isoformat()
    now = datetime.now()

    # Korean day names
    day_names = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    today_date = date.today()
    today_display = f"{today_date.month}월 {today_date.day}일"
    today_weekday = day_names[today_date.weekday()]

    with S.get_db() as conn:
        # Today counts
        today_todo_count = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE profile_id=? AND due_date=? AND completed=0",
            (pid, today_str),
        ).fetchone()[0]
        today_event_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE profile_id=? AND date(start_time)=?",
            (pid, today_str),
        ).fetchone()[0]
        overdue_count = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=0 AND due_date<? AND due_date IS NOT NULL AND due_date != ''",
            (pid, today_str),
        ).fetchone()[0]

        # Streak: consecutive days with completed todos
        streak_days = 0
        check_date = today_date
        while True:
            check_str = check_date.isoformat()
            done_count = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=1 AND date(completed_at)=?",
                (pid, check_str),
            ).fetchone()[0]
            if done_count > 0:
                streak_days += 1
                check_date -= timedelta(days=1)
            else:
                break
            if streak_days > 365:
                break

        # Upcoming 5 items
        upcoming_items = []
        # Upcoming todos with due dates
        upcoming_todos = conn.execute(
            "SELECT id, title, due_date FROM todos WHERE profile_id=? AND completed=0 AND due_date>=? AND due_date IS NOT NULL ORDER BY due_date LIMIT 5",
            (pid, today_str),
        ).fetchall()
        for t in upcoming_todos:
            upcoming_items.append({
                "title": t["title"],
                "type": "todo",
                "due": t["due_date"],
                "relative_time": _relative_time(t["due_date"], now),
            })
        # Upcoming events
        now_str = now.strftime("%Y-%m-%d %H:%M")
        upcoming_events = conn.execute(
            "SELECT id, title, start_time FROM events WHERE profile_id=? AND start_time>=? ORDER BY start_time LIMIT 5",
            (pid, now_str),
        ).fetchall()
        for ev in upcoming_events:
            upcoming_items.append({
                "title": ev["title"],
                "type": "event",
                "due": ev["start_time"],
                "relative_time": _relative_time(ev["start_time"], now),
            })
        # Sort by due time
        upcoming_items.sort(key=lambda x: x["due"])
        upcoming_items = upcoming_items[:5]

        # Today focus hours (defensive: work_logs table may not exist or lack profile_id)
        today_focus = 0
        try:
            today_focus = conn.execute(
                "SELECT COALESCE(SUM(hours), 0) FROM work_logs WHERE profile_id=? AND log_date=? AND title LIKE '%집중 모드%'",
                (pid, today_str),
            ).fetchone()[0]
        except Exception:
            pass

        # Week stats
        week_start = today_date - timedelta(days=today_date.weekday())
        week_end = week_start + timedelta(days=6)
        week_total = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE due_date BETWEEN ? AND ? AND profile_id=?",
            (week_start.isoformat(), week_end.isoformat(), pid),
        ).fetchone()[0]
        week_completed = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE due_date BETWEEN ? AND ? AND completed=1 AND profile_id=?",
            (week_start.isoformat(), week_end.isoformat(), pid),
        ).fetchone()[0]
        week_rate = round(week_completed / week_total * 100) if week_total > 0 else 0

        # Category budgets
        category_budgets = []
        cats = S.get_categories(conn, pid)
        for cat in cats:
            c = dict(cat)
            total = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE category_id=? AND profile_id=?",
                (c["id"], pid),
            ).fetchone()[0]
            done = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE category_id=? AND profile_id=? AND completed=1",
                (c["id"], pid),
            ).fetchone()[0]
            if total > 0:
                category_budgets.append({
                    "name": c["name"], "color": c["color"],
                    "pct": round(done / total * 100),
                })

    return JSONResponse({
        "today_display": today_display,
        "today_weekday": today_weekday,
        "today_todo_count": today_todo_count,
        "today_event_count": today_event_count,
        "overdue_count": overdue_count,
        "streak_days": streak_days,
        "week_rate": week_rate,
        "week_completed": week_completed,
        "week_total": week_total,
        "upcoming_items": upcoming_items,
        "today_focus_hours": round(today_focus, 1),
        "category_budgets": category_budgets,
    })


def _relative_time(dt_str: str, now: datetime) -> str:
    """Convert a date/datetime string to Korean relative time."""
    if not dt_str:
        return ""
    try:
        if "T" in dt_str or " " in dt_str:
            target = datetime.fromisoformat(dt_str.replace(" ", "T")[:19])
        else:
            target = datetime.strptime(dt_str, "%Y-%m-%d").replace(hour=23, minute=59)
    except (ValueError, TypeError):
        return dt_str
    diff = target - now
    total_seconds = diff.total_seconds()
    if total_seconds < 0:
        return "지남"
    minutes = total_seconds / 60
    hours = minutes / 60
    days = hours / 24
    if minutes < 60:
        return f"{int(minutes)}분 후"
    if hours < 24:
        return f"{int(hours)}시간 후"
    if days < 2:
        return "내일"
    if days < 7:
        return f"{int(days)}일 후"
    return dt_str[:10]


@router.get("/health")
async def health(request: Request):
    S = request.app.state
    data = {"status": "ok"}
    if hasattr(S, "app_name"):
        data["app"] = S.app_name
    return JSONResponse(data)


def _ical_escape(s: str) -> str:
    """Escape text for iCalendar RFC 5545 compliance."""
    return str(s).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _ical_fold(line: str) -> str:
    """Fold long lines per RFC 5545 (max 75 octets per line)."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts = []
    while len(encoded) > 75:
        cut = 75 if not parts else 74
        while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
            cut -= 1
        parts.append(encoded[:cut].decode("utf-8", errors="replace"))
        encoded = encoded[cut:]
    if encoded:
        parts.append(encoded.decode("utf-8", errors="replace"))
    return "\r\n ".join(parts)


def _format_ical_dt(dt_str: str) -> tuple[str, str]:
    """Convert a datetime/date string to iCal property params and value.

    Returns (property_params, value).
    Date-only: (";VALUE=DATE", "20260519")
    Datetime:  ("", "20260519T140000")
    """
    if not dt_str:
        return "", ""
    clean = dt_str.replace("-", "").replace(":", "").replace(" ", "T")
    if len(clean) == 8:
        return ";VALUE=DATE", clean
    if "T" in clean:
        parts = clean.split("T", 1)
        date_part = parts[0][:8]
        time_part = parts[1][:6].ljust(6, "0")
        return "", f"{date_part}T{time_part}"
    return ";VALUE=DATE", clean[:8]


def _priority_to_ical(priority: int) -> int:
    """Map app priority (1=high, 2=medium, 3=low) to iCal (1-9)."""
    return {1: 1, 2: 5, 3: 9}.get(priority, 5)


def _build_ical_feed(conn, pid: int, app_name: str = "Planner") -> str:
    """Build RFC 5545 compliant VCALENDAR content for a profile."""
    events = conn.execute(
        "SELECT * FROM events WHERE profile_id=? ORDER BY start_time", (pid,)
    ).fetchall()
    todos = conn.execute(
        "SELECT * FROM todos WHERE profile_id=? AND due_date IS NOT NULL AND due_date != ''",
        (pid,),
    ).fetchall()
    form_entries = conn.execute(
        "SELECT fe.id, fe.entry_date, fe.values_json, ft.name as tpl_name "
        "FROM form_entries fe JOIN form_templates ft ON fe.template_id=ft.id "
        "WHERE fe.profile_id=? AND fe.entry_date IS NOT NULL", (pid,)
    ).fetchall()

    now_stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    esc = _ical_escape

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{app_name}//iCal Export//KR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{app_name}",
        "X-WR-TIMEZONE:Asia/Seoul",
    ]

    for row in events:
        ev = dict(row)
        uid = f"event-{ev['id']}@planner"
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{now_stamp}")

        st_params, st_val = _format_ical_dt(ev["start_time"])
        if st_val:
            lines.append(f"DTSTART{st_params}:{st_val}")
        if ev.get("end_time"):
            et_params, et_val = _format_ical_dt(ev["end_time"])
            if et_val:
                lines.append(f"DTEND{et_params}:{et_val}")

        lines.append(_ical_fold(f"SUMMARY:{esc(ev['title'])}"))
        if ev.get("memo"):
            lines.append(_ical_fold(f"DESCRIPTION:{esc(ev['memo'])}"))
        if ev.get("created_at"):
            cr_params, cr_val = _format_ical_dt(ev["created_at"])
            if cr_val:
                lines.append(f"CREATED:{cr_val}")

        # RRULE for recurring events
        recurrence = ev.get("recurrence", "")
        if recurrence and recurrence != "none":
            from common.recurrence import normalize_rrule
            rrule_str = normalize_rrule(recurrence)
            if rrule_str:
                lines.append(f"RRULE:{rrule_str}")

        # VALARM: 15-minute reminder for timed events
        if ev["start_time"] and "T" in ev["start_time"]:
            lines.append("BEGIN:VALARM")
            lines.append("TRIGGER:-PT15M")
            lines.append("ACTION:DISPLAY")
            lines.append(f"DESCRIPTION:{esc(ev['title'])}")
            lines.append("END:VALARM")

        lines.append("END:VEVENT")

    for row in todos:
        td = dict(row)
        uid = f"todo-{td['id']}@planner"
        lines.append("BEGIN:VTODO")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{now_stamp}")
        dd = td["due_date"].replace("-", "")
        lines.append(f"DUE;VALUE=DATE:{dd}")
        lines.append(_ical_fold(f"SUMMARY:{esc(td['title'])}"))
        if td.get("description"):
            lines.append(_ical_fold(f"DESCRIPTION:{esc(td['description'])}"))
        lines.append(f"PRIORITY:{_priority_to_ical(td.get('priority', 2))}")
        if td.get("completed"):
            lines.append("STATUS:COMPLETED")
            if td.get("completed_at"):
                cp_params, cp_val = _format_ical_dt(td["completed_at"])
                if cp_val:
                    lines.append(f"COMPLETED:{cp_val}")
        else:
            lines.append("STATUS:NEEDS-ACTION")

        repeat_type = td.get("repeat_type", "none")
        if repeat_type and repeat_type != "none":
            from common.recurrence import normalize_rrule
            rrule_str = normalize_rrule(repeat_type)
            if rrule_str:
                lines.append(f"RRULE:{rrule_str}")

        lines.append("END:VTODO")

    for fe in form_entries:
        uid = f"form-{fe['id']}@planner"
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{now_stamp}")
        dd = fe["entry_date"].replace("-", "")
        lines.append(f"DTSTART;VALUE=DATE:{dd}")
        try:
            data = json.loads(fe["values_json"])
            summary_parts = [str(v) for v in list(data.values())[:3] if v]
            summary = f"[{fe['tpl_name']}] {' / '.join(summary_parts)}"
        except (json.JSONDecodeError, TypeError):
            summary = f"[{fe['tpl_name']}] {fe['entry_date']}"
        lines.append(_ical_fold(f"SUMMARY:{esc(summary[:100])}"))
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


@router.get("/cal/{profile_id}.ics")
async def ical_feed(request: Request, profile_id: int, token: str = ""):
    """RFC 5545 compliant iCal feed.

    Supports token-based access for calendar subscription clients.
    Use ?token=<profile_token> to bypass cookie auth.
    """
    S = request.app.state
    pid = profile_id

    # Token-based auth (if ical_tokens table exists)
    if token:
        with S.get_db() as conn:
            try:
                row = conn.execute(
                    "SELECT profile_id FROM ical_tokens WHERE profile_id=? AND token=?",
                    (pid, token),
                ).fetchone()
                if not row:
                    return Response("Forbidden", status_code=403)
            except Exception:
                pass  # Table may not exist in jm/my planners

    app_name = getattr(S, "app_name", "Planner")

    with S.get_db() as conn:
        ical_content = _build_ical_feed(conn, pid, app_name)

    return Response(
        content=ical_content.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="calendar_{profile_id}.ics"'},
    )


# ── iCal Import ──

def _parse_ical_content(content: str) -> list[dict]:
    """Parse iCal content into a list of component dicts.

    Handles VEVENT and VTODO. Supports line unfolding per RFC 5545.
    No external dependencies.
    """
    # Unfold continuation lines
    unfolded_lines = []
    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith((" ", "\t")) and unfolded_lines:
            unfolded_lines[-1] += line[1:]
        else:
            unfolded_lines.append(line)

    components = []
    current = None
    in_alarm = False

    for line in unfolded_lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped == "BEGIN:VALARM":
            in_alarm = True
            continue
        if stripped == "END:VALARM":
            in_alarm = False
            continue
        if in_alarm:
            continue

        if stripped in ("BEGIN:VEVENT", "BEGIN:VTODO"):
            current = {"_type": "event" if "VEVENT" in stripped else "todo"}
            continue
        if stripped in ("END:VEVENT", "END:VTODO"):
            if current:
                components.append(current)
            current = None
            continue

        if current is None:
            continue

        if ":" not in stripped:
            continue
        prop_part, value = stripped.split(":", 1)
        prop_name = prop_part.split(";")[0].upper()
        params = {}
        if ";" in prop_part:
            for param in prop_part.split(";")[1:]:
                if "=" in param:
                    pk, pv = param.split("=", 1)
                    params[pk.upper()] = pv

        # Unescape
        value = value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")

        if prop_name == "UID":
            current["uid"] = value
        elif prop_name == "SUMMARY":
            current["summary"] = value
        elif prop_name == "DESCRIPTION":
            current["description"] = value
        elif prop_name == "DTSTART":
            current["dtstart"] = value
            current["dtstart_date_only"] = params.get("VALUE") == "DATE"
        elif prop_name == "DTEND":
            current["dtend"] = value
        elif prop_name == "DUE":
            current["due"] = value
            current["due_date_only"] = params.get("VALUE") == "DATE"
        elif prop_name == "RRULE":
            current["rrule"] = value
        elif prop_name == "STATUS":
            current["status"] = value.upper()
        elif prop_name == "PRIORITY":
            try:
                current["priority"] = int(value)
            except ValueError:
                pass
        elif prop_name == "COMPLETED":
            current["completed_dt"] = value

    return components


def _ical_dt_to_iso(value: str, date_only: bool = False) -> str:
    """Convert iCal datetime to ISO format ('2026-05-19T14:00' or '2026-05-19')."""
    if not value:
        return ""
    value = value.rstrip("Z")
    if "T" in value and not date_only:
        date_part = value.split("T")[0]
        time_part = value.split("T")[1][:6]
        if len(date_part) >= 8 and len(time_part) >= 4:
            return (
                f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
                f"T{time_part[:2]}:{time_part[2:4]}"
            )
    clean = value.replace("-", "").replace("T", "")[:8]
    if len(clean) >= 8:
        return f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
    return ""


def _ical_priority_to_app(ical_priority: int) -> int:
    """Map iCal priority (1-9) to app priority (1=high, 2=medium, 3=low)."""
    if ical_priority <= 0:
        return 2
    if ical_priority <= 3:
        return 1
    if ical_priority <= 6:
        return 2
    return 3


@router.post("/ical/import")
async def ical_import(request: Request):
    """Import events and todos from an uploaded .ics file.

    Parses VEVENT and VTODO. Handles duplicates by UID.
    Returns JSON summary of imported items.
    """
    S = request.app.state
    pid = S.get_profile_id(request)
    if not pid:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "read"):
        return JSONResponse({"error": "No file provided"}, status_code=400)

    content = await file.read()
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    else:
        text = content

    if "BEGIN:VCALENDAR" not in text:
        return JSONResponse({"error": "Invalid iCal file"}, status_code=400)

    components = _parse_ical_content(text)

    events_imported = 0
    events_skipped = 0
    todos_imported = 0
    todos_skipped = 0

    with S.get_db() as conn:
        for comp in components:
            uid = comp.get("uid", "")

            if comp["_type"] == "event":
                if uid:
                    existing = conn.execute(
                        "SELECT id FROM events WHERE profile_id=? AND gcal_event_id=?",
                        (pid, uid),
                    ).fetchone()
                    if existing:
                        events_skipped += 1
                        continue

                title = comp.get("summary", "")
                if not title:
                    events_skipped += 1
                    continue

                start = _ical_dt_to_iso(
                    comp.get("dtstart", ""),
                    comp.get("dtstart_date_only", False),
                )
                end = _ical_dt_to_iso(comp.get("dtend", ""), False)
                description = comp.get("description", "")
                rrule = comp.get("rrule", "")

                if not start:
                    events_skipped += 1
                    continue

                conn.execute("""
                    INSERT INTO events (title, start_time, end_time, memo, profile_id,
                                       gcal_event_id, recurrence)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (title, start, end, description, pid, uid, rrule))
                events_imported += 1

            elif comp["_type"] == "todo":
                title = comp.get("summary", "")
                if not title:
                    todos_skipped += 1
                    continue

                due = _ical_dt_to_iso(
                    comp.get("due", comp.get("dtstart", "")),
                    comp.get("due_date_only", comp.get("dtstart_date_only", True)),
                )

                if uid:
                    existing = conn.execute(
                        "SELECT id FROM todos WHERE profile_id=? AND title=? AND due_date=?",
                        (pid, title, due),
                    ).fetchone()
                    if existing:
                        todos_skipped += 1
                        continue

                description = comp.get("description", "")
                priority = _ical_priority_to_app(comp.get("priority", 0))
                completed = 1 if comp.get("status") == "COMPLETED" else 0
                completed_at = ""
                if completed and comp.get("completed_dt"):
                    completed_at = _ical_dt_to_iso(comp["completed_dt"])
                elif completed:
                    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                rrule = comp.get("rrule", "")
                repeat_type = rrule if rrule else "none"

                max_order = conn.execute(
                    "SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?",
                    (pid,),
                ).fetchone()[0]

                conn.execute("""
                    INSERT INTO todos (title, description, due_date, priority, completed,
                                       completed_at, repeat_type, sort_order, profile_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (title, description, due, priority, completed, completed_at,
                      repeat_type, max_order + 1, pid))
                todos_imported += 1

    return JSONResponse({
        "ok": True,
        "events_imported": events_imported,
        "events_skipped": events_skipped,
        "todos_imported": todos_imported,
        "todos_skipped": todos_skipped,
        "total_imported": events_imported + todos_imported,
    })
