import json
from collections import OrderedDict
from datetime import date, datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from common.constants import PRIORITY_MAP, REPEAT_MAP, RRULE_FREQ_OPTIONS, RRULE_DAY_OPTIONS
from common.recurrence import next_occurrence, build_rrule, rrule_to_korean
from common.utils import clamp_text, clamp_priority, fix_mojibake, validate_date_str

router = APIRouter()


@router.get("/todos", response_class=HTMLResponse)
async def todos_page(request: Request, filter: str = "all",
                     category_id: int = None, assignee: str = None,
                     energy: int = None):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        today_str = date.today().isoformat()
        where = "1=1"
        params: list = []

        if filter == "completed":
            where = "t.completed = 1"
        elif filter == "active":
            where = "t.completed = 0"
        elif filter == "overdue":
            where = "t.completed = 0 AND t.due_date < ? AND t.due_date IS NOT NULL"
            params.append(today_str)

        where += " AND t.profile_id = ?"
        params.append(pid)

        if category_id:
            where += " AND t.category_id = ?"
            params.append(category_id)

        if assignee:
            where += " AND t.assignee = ?"
            params.append(assignee)

        if energy in (1, 2, 3):
            where += " AND t.energy_level = ?"
            params.append(energy)

        todos = conn.execute(f"""
            SELECT t.*, c.name as category_name, c.color as category_color
            FROM todos t LEFT JOIN categories c ON t.category_id = c.id
            WHERE {where}
            ORDER BY t.completed ASC,
                     CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END,
                     t.due_date ASC, t.priority ASC, t.sort_order ASC
        """, params).fetchall()

        categories = S.get_categories(conn, pid)

        grouped: OrderedDict[str, list] = OrderedDict()
        for t in todos:
            td = dict(t)
            subs = conn.execute(
                "SELECT * FROM subtasks WHERE todo_id=? ORDER BY sort_order, id", (td["id"],)
            ).fetchall()
            td["subtasks"] = [dict(s) for s in subs]
            key = td.get("due_date") or ""
            grouped.setdefault(key, []).append(td)

    return S.render(request, "todos.html", {
        "page": "todos",
        "todo_groups": grouped,
        "todo_count": sum(len(v) for v in grouped.values()),
        "categories": [dict(c) for c in categories],
        "current_filter": filter,
        "current_category_id": category_id,
        "current_assignee": assignee,
        "current_energy": energy,
        "priority_map": PRIORITY_MAP,
        "repeat_map": REPEAT_MAP,
        "rrule_freq_options": RRULE_FREQ_OPTIONS,
        "rrule_day_options": RRULE_DAY_OPTIONS,
        "rrule_to_korean": rrule_to_korean,
    })


@router.post("/todos", response_class=HTMLResponse)
async def create_todo(request: Request,
                      title: str = Form(...),
                      description: str = Form(""),
                      due_date: str = Form(""),
                      priority: int = Form(2),
                      category_id: str = Form(""),
                      tags: str = Form(""),
                      repeat_type: str = Form("none"),
                      recurrence_end: str = Form(""),
                      assignee: str = Form(""),
                      energy_level: int = Form(2),
                      rrule_freq: str = Form(""),
                      rrule_interval: int = Form(1),
                      rrule_byday: str = Form(""),
                      rrule_bymonthday: str = Form(""),
                      rrule_end_type: str = Form("never"),
                      rrule_count: int = Form(0),
                      rrule_until: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200).strip()
    if not title:
        return S.redirect(request, "/todos")
    description = clamp_text(fix_mojibake(description), 2000)
    assignee = clamp_text(fix_mojibake(assignee), 100)
    priority = clamp_priority(priority)
    due_date = validate_date_str(due_date)
    recurrence_end = validate_date_str(recurrence_end) or ""
    energy_level = max(1, min(3, energy_level))

    # Build RRULE from custom fields if repeat_type is 'custom'
    if repeat_type == "custom" and rrule_freq:
        byday = [d.strip() for d in rrule_byday.split(",") if d.strip()] if rrule_byday else []
        bymonthday_list = [int(d.strip()) for d in rrule_bymonthday.split(",") if d.strip().isdigit()] if rrule_bymonthday else []
        count_val = rrule_count if rrule_end_type == "count" and rrule_count > 0 else None
        until_val = validate_date_str(rrule_until) if rrule_end_type == "until" else None
        repeat_type = build_rrule(rrule_freq, rrule_interval, byday, bymonthday_list, count_val, until_val)
        if not repeat_type:
            repeat_type = "none"

    tag_list = [t.strip() for t in fix_mojibake(tags).split(",") if t.strip()] if tags else []
    cat_id = int(category_id) if category_id else None

    with S.get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
        cur = conn.execute("""
            INSERT INTO todos (title, description, due_date, priority, category_id, tags, repeat_type, recurrence_end, assignee, sort_order, profile_id, energy_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, description, due_date, priority, cat_id, json.dumps(tag_list), repeat_type, recurrence_end, assignee, max_order + 1, pid, energy_level))
        S.audit_log(conn, "todo", cur.lastrowid, "create", {"title": title}, str(pid))

    return S.redirect(request, "/todos")


@router.post("/todos/{todo_id}/toggle", response_class=HTMLResponse)
async def toggle_todo(request: Request, todo_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        todo = conn.execute("SELECT * FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        if not todo:
            raise HTTPException(404)
        new_status = 0 if todo["completed"] else 1
        completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if new_status else None
        conn.execute(
            "UPDATE todos SET completed=?, completed_at=?, updated_at=datetime('now','localtime') WHERE id=? AND profile_id=?",
            (new_status, completed_at, todo_id, pid),
        )
        S.audit_log(conn, "todo", todo_id, "complete" if new_status else "uncomplete", {"title": todo["title"]}, str(pid))

        # Handle repeat
        if new_status == 1 and todo["repeat_type"] != "none" and todo["due_date"]:
            nxt = next_occurrence(todo["due_date"], todo["repeat_type"])
            rec_end = todo["recurrence_end"] if "recurrence_end" in todo.keys() else ""
            if nxt and (not rec_end or nxt <= rec_end):
                max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
                conn.execute("""
                    INSERT INTO todos (title, description, due_date, priority, category_id, tags, repeat_type, recurrence_end, assignee, sort_order, profile_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (todo["title"], todo["description"], nxt,
                      todo["priority"], todo["category_id"], todo["tags"],
                      todo["repeat_type"], rec_end, todo["assignee"], max_order + 1, todo["profile_id"]))

    if request.headers.get("HX-Request"):
        with S.get_db() as conn:
            updated = conn.execute(
                "SELECT t.*, c.name as category_name, c.color as category_color FROM todos t LEFT JOIN categories c ON t.category_id=c.id WHERE t.id=? AND t.profile_id=?",
                (todo_id, pid),
            ).fetchone()
            if updated:
                td = dict(updated)
                td["subtasks"] = [dict(s) for s in conn.execute("SELECT * FROM subtasks WHERE todo_id=? ORDER BY sort_order, id", (todo_id,)).fetchall()]
                return S.render(request, "partials/todo_item.html", {"todo": td, "priority_map": PRIORITY_MAP, "repeat_map": REPEAT_MAP, "rrule_to_korean": rrule_to_korean, "today": date.today()})
        return HTMLResponse("")

    referer = request.headers.get("HX-Current-URL") or request.headers.get("referer") or ""
    if "/calendar" in referer:
        return S.redirect(request, "/calendar")
    if "plan_view" in referer:
        return S.redirect(request, "/")
    return S.redirect(request, "/todos")


@router.get("/todos/{todo_id}/edit", response_class=HTMLResponse)
async def edit_todo_form(request: Request, todo_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        todo = conn.execute("SELECT * FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        if not todo:
            raise HTTPException(404)
        categories = S.get_categories(conn, pid)
    return S.render(request, "partials/todo_edit_form.html", {
        "todo": dict(todo),
        "categories": [dict(c) for c in categories],
        "priority_map": PRIORITY_MAP,
        "repeat_map": REPEAT_MAP,
        "rrule_freq_options": RRULE_FREQ_OPTIONS,
        "rrule_day_options": RRULE_DAY_OPTIONS,
        "rrule_to_korean": rrule_to_korean,
    })


@router.put("/todos/{todo_id}", response_class=HTMLResponse)
async def update_todo(request: Request, todo_id: int,
                      title: str = Form(...),
                      description: str = Form(""),
                      due_date: str = Form(""),
                      priority: int = Form(2),
                      category_id: str = Form(""),
                      tags: str = Form(""),
                      repeat_type: str = Form("none"),
                      recurrence_end: str = Form(""),
                      assignee: str = Form(""),
                      energy_level: int = Form(2),
                      rrule_freq: str = Form(""),
                      rrule_interval: int = Form(1),
                      rrule_byday: str = Form(""),
                      rrule_bymonthday: str = Form(""),
                      rrule_end_type: str = Form("never"),
                      rrule_count: int = Form(0),
                      rrule_until: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    description = clamp_text(fix_mojibake(description), 2000)
    assignee = clamp_text(fix_mojibake(assignee), 100)
    priority = clamp_priority(priority)
    due_date = validate_date_str(due_date)
    recurrence_end = validate_date_str(recurrence_end) or ""
    energy_level = max(1, min(3, energy_level))

    # Build RRULE from custom fields if repeat_type is 'custom'
    if repeat_type == "custom" and rrule_freq:
        byday = [d.strip() for d in rrule_byday.split(",") if d.strip()] if rrule_byday else []
        bymonthday_list = [int(d.strip()) for d in rrule_bymonthday.split(",") if d.strip().isdigit()] if rrule_bymonthday else []
        count_val = rrule_count if rrule_end_type == "count" and rrule_count > 0 else None
        until_val = validate_date_str(rrule_until) if rrule_end_type == "until" else None
        repeat_type = build_rrule(rrule_freq, rrule_interval, byday, bymonthday_list, count_val, until_val)
        if not repeat_type:
            repeat_type = "none"

    tag_list = [t.strip() for t in fix_mojibake(tags).split(",") if t.strip()] if tags else []
    cat_id = int(category_id) if category_id else None

    with S.get_db() as conn:
        old = conn.execute("SELECT title, description, due_date, priority FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        conn.execute("""
            UPDATE todos SET title=?, description=?, due_date=?, priority=?, category_id=?,
                   tags=?, repeat_type=?, recurrence_end=?, assignee=?, energy_level=?, updated_at=datetime('now','localtime')
            WHERE id=? AND profile_id=?
        """, (title, description, due_date, priority, cat_id, json.dumps(tag_list), repeat_type, recurrence_end, assignee, energy_level, todo_id, pid))
        changes = {}
        if old:
            if old["title"] != title:
                changes["title"] = {"old": old["title"], "new": title}
            if old["description"] != description:
                changes["description"] = {"old": old["description"][:50], "new": description[:50]}
            if old["due_date"] != due_date:
                changes["due_date"] = {"old": old["due_date"], "new": due_date}
            if old["priority"] != priority:
                changes["priority"] = {"old": old["priority"], "new": priority}
        S.audit_log(conn, "todo", todo_id, "update", changes, str(pid))

    return S.redirect(request, "/todos")


@router.delete("/todos/{todo_id}", response_class=HTMLResponse)
async def delete_todo(request: Request, todo_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        old = conn.execute("SELECT title FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        conn.execute("DELETE FROM todos WHERE id=? AND profile_id=?", (todo_id, pid))
        S.audit_log(conn, "todo", todo_id, "delete", {"title": old["title"]} if old else {}, str(pid))
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return S.redirect(request, "/todos")


@router.post("/todos/reorder", response_class=HTMLResponse)
async def reorder_todos(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    body = await request.json()
    order = body.get("order", [])
    with S.get_db() as conn:
        for idx, tid in enumerate(order):
            conn.execute("UPDATE todos SET sort_order=? WHERE id=? AND profile_id=?", (idx, int(tid), pid))
    return JSONResponse({"ok": True})


@router.post("/todos/bulk", response_class=HTMLResponse)
async def bulk_todo_action(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    body = await request.json()
    action = body.get("action")
    ids = [int(i) for i in body.get("ids", []) if str(i).isdigit()]
    if not ids or action not in ("complete", "delete"):
        return JSONResponse({"ok": False})
    placeholders = ",".join("?" * len(ids))
    with S.get_db() as conn:
        if action == "complete":
            conn.execute(f"UPDATE todos SET completed=1 WHERE id IN ({placeholders}) AND profile_id=?", (*ids, pid))
        elif action == "delete":
            conn.execute(f"DELETE FROM subtasks WHERE todo_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM todos WHERE id IN ({placeholders}) AND profile_id=?", (*ids, pid))
    return JSONResponse({"ok": True})


# ── Subtasks ──

@router.post("/todos/{todo_id}/subtasks", response_class=HTMLResponse)
async def add_subtask(request: Request, todo_id: int, title: str = Form(...)):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    with S.get_db() as conn:
        parent = conn.execute("SELECT id FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        if not parent:
            raise HTTPException(404)
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM subtasks WHERE todo_id=?", (todo_id,)).fetchone()[0]
        conn.execute("INSERT INTO subtasks (todo_id, title, sort_order) VALUES (?,?,?)", (todo_id, title, max_order + 1))
    return S.redirect(request, "/todos")


@router.post("/subtasks/{sub_id}/toggle", response_class=HTMLResponse)
async def toggle_subtask(request: Request, sub_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        sub = conn.execute(
            "SELECT s.* FROM subtasks s JOIN todos t ON s.todo_id=t.id WHERE s.id=? AND t.profile_id=?",
            (sub_id, pid),
        ).fetchone()
        if sub:
            conn.execute("UPDATE subtasks SET completed=? WHERE id=?", (0 if sub["completed"] else 1, sub_id))
            if request.headers.get("HX-Request"):
                todo_id = sub["todo_id"]
                updated = conn.execute(
                    "SELECT t.*, c.name as category_name, c.color as category_color FROM todos t LEFT JOIN categories c ON t.category_id=c.id WHERE t.id=? AND t.profile_id=?",
                    (todo_id, pid),
                ).fetchone()
                if updated:
                    td = dict(updated)
                    td["subtasks"] = [dict(s) for s in conn.execute("SELECT * FROM subtasks WHERE todo_id=? ORDER BY sort_order, id", (todo_id,)).fetchall()]
                    return S.render(request, "partials/todo_item.html", {"todo": td, "priority_map": PRIORITY_MAP, "repeat_map": REPEAT_MAP, "rrule_to_korean": rrule_to_korean, "today": date.today()})
    return S.redirect(request, "/todos")


@router.delete("/subtasks/{sub_id}", response_class=HTMLResponse)
async def delete_subtask(request: Request, sub_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        sub = conn.execute(
            "SELECT s.id FROM subtasks s JOIN todos t ON s.todo_id=t.id WHERE s.id=? AND t.profile_id=?",
            (sub_id, pid),
        ).fetchone()
        if sub:
            conn.execute("DELETE FROM subtasks WHERE id=?", (sub_id,))
    return HTMLResponse("")
