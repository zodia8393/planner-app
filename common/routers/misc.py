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
    with S.get_db() as conn:
        conn.execute(
            "INSERT INTO work_logs (profile_id, log_date, title, content, hours, category_id) VALUES (?,?,?,?,?,?)",
            (pid, date.today().isoformat(), title, f"집중 모드 {minutes}분 완료", hours, cat_id))
    return JSONResponse({"ok": True, "hours": hours})


@router.get("/api/reminders")
async def get_reminders(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    today_str = date.today().isoformat()
    reminders = []
    with S.get_db() as conn:
        # Overdue todos
        overdue = conn.execute(
            "SELECT id, title, due_date FROM todos WHERE profile_id=? AND completed=0 AND due_date < ? AND due_date IS NOT NULL AND due_date != '' ORDER BY due_date LIMIT 10",
            (pid, today_str),
        ).fetchall()
        for t in overdue:
            reminders.append({"type": "overdue", "id": t["id"], "title": t["title"], "due_date": t["due_date"]})
        # Today's todos
        today_todos = conn.execute(
            "SELECT id, title FROM todos WHERE profile_id=? AND completed=0 AND due_date=? ORDER BY priority, sort_order LIMIT 10",
            (pid, today_str),
        ).fetchall()
        for t in today_todos:
            reminders.append({"type": "today", "id": t["id"], "title": t["title"]})
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


@router.get("/health")
async def health(request: Request):
    S = request.app.state
    data = {"status": "ok"}
    if hasattr(S, "app_name"):
        data["app"] = S.app_name
    return JSONResponse(data)


@router.get("/cal/{profile_id}.ics")
async def ical_feed(request: Request, profile_id: int):
    S = request.app.state
    pid = profile_id
    with S.get_db() as conn:
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

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Planner//iCal//KR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    def esc(s):
        return str(s).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    for ev in events:
        uid = f"event-{ev['id']}@planner"
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        st = ev["start_time"].replace("-", "").replace(":", "").replace(" ", "T")
        if len(st) == 8:
            lines.append(f"DTSTART;VALUE=DATE:{st}")
        else:
            lines.append(f"DTSTART:{st}")
        if ev["end_time"]:
            et = ev["end_time"].replace("-", "").replace(":", "").replace(" ", "T")
            lines.append(f"DTEND:{et}")
        lines.append(f"SUMMARY:{esc(ev['title'])}")
        if ev["memo"]:
            lines.append(f"DESCRIPTION:{esc(ev['memo'])}")
        lines.append("END:VEVENT")

    for td in todos:
        uid = f"todo-{td['id']}@planner"
        lines.append("BEGIN:VTODO")
        lines.append(f"UID:{uid}")
        dd = td["due_date"].replace("-", "")
        lines.append(f"DUE;VALUE=DATE:{dd}")
        lines.append(f"SUMMARY:{esc(td['title'])}")
        if td["completed"]:
            lines.append("STATUS:COMPLETED")
        else:
            lines.append("STATUS:NEEDS-ACTION")
        lines.append("END:VTODO")

    for fe in form_entries:
        uid = f"form-{fe['id']}@planner"
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        dd = fe["entry_date"].replace("-", "")
        lines.append(f"DTSTART;VALUE=DATE:{dd}")
        try:
            data = json.loads(fe["values_json"])
            summary_parts = [str(v) for v in list(data.values())[:3] if v]
            summary = f"[{fe['tpl_name']}] {' / '.join(summary_parts)}"
        except (json.JSONDecodeError, TypeError):
            summary = f"[{fe['tpl_name']}] {fe['entry_date']}"
        lines.append(f"SUMMARY:{esc(summary[:100])}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    ical_content = "\r\n".join(lines)
    return Response(
        content=ical_content.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="calendar_{profile_id}.ics"'},
    )
