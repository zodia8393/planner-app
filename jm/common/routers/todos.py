import json
from collections import OrderedDict
from datetime import date, datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from common.constants import PRIORITY_MAP, REPEAT_MAP, RRULE_FREQ_OPTIONS, RRULE_DAY_OPTIONS
from common.nlp_date import extract_date_from_text
from common.recurrence import next_occurrence, build_rrule, parse_rrule, rrule_to_korean
from common.utils import clamp_text, clamp_priority, fix_mojibake, validate_date_str, safe_int
from common.filters import parse_tags

router = APIRouter()


@router.get("/todos", response_class=HTMLResponse)
async def todos_page(request: Request, filter: str = "all",
                     category_id: str = None, assignee: str = None,
                     energy: int = None, tag: str = None):
    S = request.app.state
    pid = S.get_profile_id(request)
    cat_id_int = safe_int(category_id)
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

        if cat_id_int:
            where += " AND t.category_id = ?"
            params.append(cat_id_int)

        if assignee:
            where += " AND t.assignee = ?"
            params.append(assignee)

        if energy in (1, 2, 3):
            where += " AND t.energy_level = ?"
            params.append(energy)

        # Item 18: Tag filter
        if tag:
            where += " AND t.tags LIKE ?"
            params.append(f'%"{tag}"%')

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
        todo_list = [dict(t) for t in todos]
        todo_ids = [t["id"] for t in todo_list]
        subs_by_todo: dict[int, list] = {}
        if todo_ids:
            ph = ",".join("?" * len(todo_ids))
            all_subs = conn.execute(
                f"SELECT * FROM subtasks WHERE todo_id IN ({ph}) ORDER BY sort_order, id", todo_ids
            ).fetchall()
            for s in all_subs:
                subs_by_todo.setdefault(s["todo_id"], []).append(dict(s))
        for td in todo_list:
            td["subtasks"] = subs_by_todo.get(td["id"], [])
            key = td.get("due_date") or ""
            grouped.setdefault(key, []).append(td)

    return S.render(request, "todos.html", {
        "page": "todos",
        "todo_groups": grouped,
        "todo_count": sum(len(v) for v in grouped.values()),
        "categories": [dict(c) for c in categories],
        "current_filter": filter,
        "current_category_id": cat_id_int,
        "current_assignee": assignee,
        "current_energy": energy,
        "current_tag": tag,
        "priority_map": PRIORITY_MAP,
        "repeat_map": REPEAT_MAP,
        "rrule_freq_options": RRULE_FREQ_OPTIONS,
        "rrule_day_options": RRULE_DAY_OPTIONS,
        "rrule_to_korean": rrule_to_korean,
    })


def _classify_kanban_column(todo: dict) -> str:
    """Determine kanban column from todo state and tags."""
    if todo.get("completed"):
        return "done"
    tags = parse_tags(todo.get("tags", "[]"))
    if "진행중" in tags:
        return "in_progress"
    return "todo"


@router.get("/todos/kanban", response_class=HTMLResponse)
async def kanban_page(request: Request, group_by: str = ""):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        todos = conn.execute("""
            SELECT t.*, c.name as category_name, c.color as category_color
            FROM todos t LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.profile_id = ?
            ORDER BY t.priority ASC, t.sort_order ASC
        """, (pid,)).fetchall()
        categories = S.get_categories(conn, pid)

        columns = OrderedDict([
            ("todo", {"label": "할 일", "todos": []}),
            ("in_progress", {"label": "진행중", "todos": []}),
            ("done", {"label": "완료", "todos": []}),
        ])
        kanban_list = [dict(t) for t in todos]
        kanban_ids = [t["id"] for t in kanban_list]
        kanban_subs: dict[int, list] = {}
        if kanban_ids:
            ph = ",".join("?" * len(kanban_ids))
            all_subs = conn.execute(
                f"SELECT * FROM subtasks WHERE todo_id IN ({ph}) ORDER BY sort_order, id", kanban_ids
            ).fetchall()
            for s in all_subs:
                kanban_subs.setdefault(s["todo_id"], []).append(dict(s))
        for td in kanban_list:
            td["subtasks"] = kanban_subs.get(td["id"], [])
            col = _classify_kanban_column(td)
            columns[col]["todos"].append(td)

        swimlanes = {}
        if group_by == "category":
            for col_key, col_data in columns.items():
                grouped = OrderedDict()
                grouped["미분류"] = []
                for cat in categories:
                    grouped[dict(cat)["name"]] = []
                for item in col_data["todos"]:
                    cat_name = item.get("category_name") or "미분류"
                    grouped.setdefault(cat_name, []).append(item)
                swimlanes[col_key] = grouped

    return S.render(request, "kanban.html", {
        "page": "todos",
        "columns": columns,
        "swimlanes": swimlanes if group_by == "category" else {},
        "group_by": group_by,
        "categories": [dict(c) for c in categories],
        "priority_map": PRIORITY_MAP,
        "todo_count": sum(len(c["todos"]) for c in columns.values()),
    })


@router.post("/todos/{todo_id}/move", response_class=HTMLResponse)
async def move_todo(request: Request, todo_id: int, column: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    if column not in ("todo", "in_progress", "done"):
        raise HTTPException(400, "Invalid column")
    with S.get_db() as conn:
        todo = conn.execute(
            "SELECT * FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)
        ).fetchone()
        if not todo:
            return S.redirect(request, "/todos")

        tags = parse_tags(todo["tags"])

        if column == "todo":
            tags = [t for t in tags if t != "진행중"]
            new_completed = 0
            completed_at = None
        elif column == "in_progress":
            if "진행중" not in tags:
                tags.append("진행중")
            new_completed = 0
            completed_at = None
        else:  # done
            tags = [t for t in tags if t != "진행중"]
            new_completed = 1
            completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            "UPDATE todos SET completed=?, completed_at=?, tags=?, updated_at=datetime('now','localtime') WHERE id=? AND profile_id=?",
            (new_completed, completed_at, json.dumps(tags), todo_id, pid),
        )
        S.audit_log(conn, "todo", todo_id, "move", {"column": column}, str(pid))

    return S.redirect(request, "/todos/kanban")


@router.post("/todos", response_class=HTMLResponse)
async def create_todo(request: Request,
                      title: str = Form(""),
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
                      rrule_until: str = Form(""),
                      reminder_offsets: str = Form("")):
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
    ro = reminder_offsets.strip() if reminder_offsets else None
    if ro in ("", "[]"):
        ro = None

    # NLP date extraction: if no explicit due_date, try parsing from title
    if not due_date:
        nlp_date, remaining_title = extract_date_from_text(title)
        if nlp_date and remaining_title:
            due_date = nlp_date.isoformat()
            title = remaining_title

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
    cat_id = safe_int(category_id)

    with S.get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
        cur = conn.execute("""
            INSERT INTO todos (title, description, due_date, priority, category_id, tags, repeat_type, recurrence_end, assignee, sort_order, profile_id, energy_level, reminder_offsets)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, description, due_date, priority, cat_id, json.dumps(tag_list), repeat_type, recurrence_end, assignee, max_order + 1, pid, energy_level, ro))
        S.audit_log(conn, "todo", cur.lastrowid, "create", {"title": title}, str(pid))

    S.event_bus.emit("todo", {"action": "created", "title": title})
    return S.redirect(request, "/todos")


@router.post("/todos/{todo_id}/toggle", response_class=HTMLResponse)
async def toggle_todo(request: Request, todo_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        todo = conn.execute("SELECT * FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        if not todo:
            return S.redirect(request, "/todos")
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

    S.event_bus.emit("todo", {"action": "toggled", "id": todo_id, "completed": new_status})

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


def _enrich_todo_rrule(td: dict) -> dict:
    """Add parsed RRULE helper fields to a todo dict for template rendering."""
    rt = td.get("repeat_type", "")
    if rt and rt.startswith("FREQ="):
        params = parse_rrule(rt)
        td["_rrule_freq"] = params["freq"]
        td["_rrule_interval"] = params["interval"]
        td["_rrule_byday"] = params["byday"]
        td["_rrule_bymonthday_str"] = ",".join(str(d) for d in params["bymonthday"])
        td["_rrule_count"] = params["count"]
        td["_rrule_until"] = params["until"].isoformat() if params["until"] else ""
    return td


@router.get("/todos/{todo_id}/edit", response_class=HTMLResponse)
async def edit_todo_form(request: Request, todo_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        todo = conn.execute("SELECT * FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        if not todo:
            return HTMLResponse("")
        categories = S.get_categories(conn, pid)
        subtasks = [dict(s) for s in conn.execute(
            "SELECT * FROM subtasks WHERE todo_id=? ORDER BY sort_order, id", (todo_id,)
        ).fetchall()]
    td = _enrich_todo_rrule(dict(todo))
    td["subtasks"] = subtasks
    return S.render(request, "partials/todo_edit_form.html", {
        "todo": td,
        "categories": [dict(c) for c in categories],
        "priority_map": PRIORITY_MAP,
        "repeat_map": REPEAT_MAP,
        "rrule_freq_options": RRULE_FREQ_OPTIONS,
        "rrule_day_options": RRULE_DAY_OPTIONS,
        "rrule_to_korean": rrule_to_korean,
    })


@router.put("/todos/{todo_id}", response_class=HTMLResponse)
async def update_todo(request: Request, todo_id: int,
                      title: str = Form(""),
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
                      rrule_until: str = Form(""),
                      reminder_offsets: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200).strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목은 필수입니다")
    description = clamp_text(fix_mojibake(description), 2000)
    assignee = clamp_text(fix_mojibake(assignee), 100)
    priority = clamp_priority(priority)
    due_date = validate_date_str(due_date)
    recurrence_end = validate_date_str(recurrence_end) or ""
    energy_level = max(1, min(3, energy_level))
    ro = reminder_offsets.strip() if reminder_offsets else None
    if ro in ("", "[]"):
        ro = None

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
    cat_id = safe_int(category_id)

    with S.get_db() as conn:
        old = conn.execute("SELECT title, description, due_date, priority FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        conn.execute("""
            UPDATE todos SET title=?, description=?, due_date=?, priority=?, category_id=?,
                   tags=?, repeat_type=?, recurrence_end=?, assignee=?, energy_level=?, reminder_offsets=?, updated_at=datetime('now','localtime')
            WHERE id=? AND profile_id=?
        """, (title, description, due_date, priority, cat_id, json.dumps(tag_list), repeat_type, recurrence_end, assignee, energy_level, ro, todo_id, pid))
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

    S.event_bus.emit("todo", {"action": "updated", "id": todo_id, "title": title})
    return S.redirect(request, "/todos")


@router.delete("/todos/{todo_id}", response_class=HTMLResponse)
async def delete_todo(request: Request, todo_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        old = conn.execute("SELECT title FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        conn.execute("DELETE FROM todos WHERE id=? AND profile_id=?", (todo_id, pid))
        S.audit_log(conn, "todo", todo_id, "delete", {"title": old["title"]} if old else {}, str(pid))
    S.event_bus.emit("todo", {"action": "deleted", "id": todo_id})
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
            int_tid = safe_int(tid)
            if int_tid is not None:
                conn.execute("UPDATE todos SET sort_order=? WHERE id=? AND profile_id=?", (idx, int_tid, pid))
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

def _render_todo_item(S, request, conn, todo_id: int, pid: int):
    """Helper: fetch a single todo with subtasks and render todo_item partial."""
    updated = conn.execute(
        "SELECT t.*, c.name as category_name, c.color as category_color "
        "FROM todos t LEFT JOIN categories c ON t.category_id=c.id "
        "WHERE t.id=? AND t.profile_id=?",
        (todo_id, pid),
    ).fetchone()
    if not updated:
        return HTMLResponse("")
    td = dict(updated)
    td["subtasks"] = [dict(s) for s in conn.execute(
        "SELECT * FROM subtasks WHERE todo_id=? ORDER BY sort_order, id", (todo_id,)
    ).fetchall()]
    return S.render(request, "partials/todo_item.html", {
        "todo": td, "priority_map": PRIORITY_MAP,
        "repeat_map": REPEAT_MAP, "rrule_to_korean": rrule_to_korean,
        "today": date.today(),
    })


@router.post("/todos/{todo_id}/subtasks", response_class=HTMLResponse)
async def add_subtask(request: Request, todo_id: int, title: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200).strip()
    if not title:
        if request.headers.get("HX-Request"):
            with S.get_db() as conn:
                return _render_todo_item(S, request, conn, todo_id, pid)
        return S.redirect(request, "/todos")
    with S.get_db() as conn:
        parent = conn.execute("SELECT id FROM todos WHERE id=? AND profile_id=?", (todo_id, pid)).fetchone()
        if not parent:
            return S.redirect(request, "/todos")
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM subtasks WHERE todo_id=?", (todo_id,)).fetchone()[0]
        conn.execute("INSERT INTO subtasks (todo_id, title, sort_order) VALUES (?,?,?)", (todo_id, title, max_order + 1))
        if request.headers.get("HX-Request"):
            return _render_todo_item(S, request, conn, todo_id, pid)
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
                return _render_todo_item(S, request, conn, sub["todo_id"], pid)
    return S.redirect(request, "/todos")


@router.put("/subtasks/{sub_id}", response_class=HTMLResponse)
async def update_subtask(request: Request, sub_id: int, title: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200).strip()
    with S.get_db() as conn:
        sub = conn.execute(
            "SELECT s.* FROM subtasks s JOIN todos t ON s.todo_id=t.id WHERE s.id=? AND t.profile_id=?",
            (sub_id, pid),
        ).fetchone()
        if not sub:
            return HTMLResponse("")
        if title:
            conn.execute("UPDATE subtasks SET title=? WHERE id=?", (title, sub_id))
        if request.headers.get("HX-Request"):
            return _render_todo_item(S, request, conn, sub["todo_id"], pid)
    return S.redirect(request, "/todos")


@router.delete("/subtasks/{sub_id}", response_class=HTMLResponse)
async def delete_subtask(request: Request, sub_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        sub = conn.execute(
            "SELECT s.todo_id FROM subtasks s JOIN todos t ON s.todo_id=t.id WHERE s.id=? AND t.profile_id=?",
            (sub_id, pid),
        ).fetchone()
        if sub:
            todo_id = sub["todo_id"]
            conn.execute("DELETE FROM subtasks WHERE id=?", (sub_id,))
            if request.headers.get("HX-Request"):
                return _render_todo_item(S, request, conn, todo_id, pid)
    return HTMLResponse("")
