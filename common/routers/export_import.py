"""Export/Import/Quick-add router — /api/export/*, /api/import/*, /api/quick-add."""

import io

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from common.utils import clamp_text, clamp_priority, fix_mojibake, validate_date_str, safe_int

router = APIRouter()


@router.post("/api/quick-add", response_class=JSONResponse)
async def api_quick_add(request: Request):
    """Quick-add a todo from command palette. Supports NLP date parsing."""
    S = request.app.state
    pid = S.get_profile_id(request)
    body = await request.json()
    title = clamp_text(fix_mojibake(body.get("title", "")), 200).strip()
    if not title:
        return JSONResponse({"ok": False, "error": "제목이 필요합니다"}, status_code=400)

    from common.nlp_date import extract_date_from_text
    parsed_date, remaining_text = extract_date_from_text(title)
    due_date = parsed_date.isoformat() if parsed_date else None
    clean_title = remaining_text.strip() or title

    with S.get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
        conn.execute(
            "INSERT INTO todos (title, due_date, priority, sort_order, profile_id) VALUES (?,?,?,?,?)",
            (clean_title, due_date, 2, max_order + 1, pid),
        )
        todo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        audit_log = getattr(S, "audit_log", None)
        if audit_log:
            audit_log(conn, "todo", todo_id, "create", {"title": clean_title, "source": "quick-add"})
    event_bus = getattr(S, "event_bus", None)
    if event_bus:
        event_bus.emit("todo", {"action": "created", "id": todo_id})
    return JSONResponse({"ok": True, "id": todo_id, "title": clean_title, "due_date": due_date})


@router.post("/api/import/todos", response_class=JSONResponse)
async def api_import_todos(request: Request):
    """Import todos from CSV (Todoist format or generic)."""
    S = request.app.state
    pid = S.get_profile_id(request)
    form = await request.form()
    file = form.get("file")
    source = form.get("source", "csv")
    if not file:
        return JSONResponse({"ok": False, "error": "파일이 필요합니다"}, status_code=400)

    import csv as csv_mod
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv_mod.DictReader(io.StringIO(content))

    count = 0
    with S.get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
        for row in reader:
            if source == "todoist":
                title = row.get("Content", row.get("content", "")).strip()
                due = row.get("Due Date", row.get("due_date", "")).strip()
                pri_str = row.get("Priority", row.get("priority", "")).strip()
                pri_map = {"4": 0, "3": 1, "2": 2, "1": 3}
                priority = int(pri_map.get(pri_str, 2))
            else:
                title = (row.get("title", "") or row.get("Title", "") or "").strip()
                due = (row.get("due_date", "") or row.get("Due Date", "") or "").strip()
                priority = safe_int(row.get("priority", "2"), 2)

            if not title:
                continue
            if due and not validate_date_str(due):
                due = None

            max_order += 1
            conn.execute(
                "INSERT INTO todos (title, due_date, priority, sort_order, profile_id) VALUES (?,?,?,?,?)",
                (clamp_text(title, 200), due or None, clamp_priority(priority), max_order, pid),
            )
            count += 1
    return JSONResponse({"ok": True, "count": count})


@router.get("/api/export/todos")
async def api_export_todos(request: Request):
    """Export all todos as CSV."""
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        rows = conn.execute(
            "SELECT t.title, t.due_date, t.priority, t.completed, t.completed_at, c.name as category "
            "FROM todos t LEFT JOIN categories c ON t.category_id=c.id WHERE t.profile_id=? ORDER BY t.created_at",
            (pid,),
        ).fetchall()

    output = io.StringIO()
    import csv as csv_mod
    writer = csv_mod.writer(output)
    writer.writerow(["title", "due_date", "priority", "completed", "completed_at", "category"])
    for r in rows:
        writer.writerow([r["title"], r["due_date"] or "", r["priority"], r["completed"], r["completed_at"] or "", r["category"] or ""])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=todos_export.csv"},
    )


@router.get("/api/export/habits")
async def api_export_habits(request: Request):
    """Export habit logs as CSV."""
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        rows = conn.execute(
            "SELECT h.name, hl.log_date, hl.count, hl.completed "
            "FROM habit_logs hl JOIN habits h ON hl.habit_id=h.id WHERE hl.profile_id=? ORDER BY hl.log_date",
            (pid,),
        ).fetchall()

    output = io.StringIO()
    import csv as csv_mod
    writer = csv_mod.writer(output)
    writer.writerow(["habit_name", "date", "count", "completed"])
    for r in rows:
        writer.writerow([r["name"], r["log_date"], r["count"], r["completed"]])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=habits_export.csv"},
    )


@router.get("/api/export/worklogs")
async def api_export_worklogs(request: Request):
    """Export work logs as CSV."""
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        rows = conn.execute(
            "SELECT wl.log_date, wl.title, wl.content, wl.hours, c.name as category "
            "FROM work_logs wl LEFT JOIN categories c ON wl.category_id=c.id WHERE wl.profile_id=? ORDER BY wl.log_date",
            (pid,),
        ).fetchall()

    output = io.StringIO()
    import csv as csv_mod
    writer = csv_mod.writer(output)
    writer.writerow(["date", "title", "content", "hours", "category"])
    for r in rows:
        writer.writerow([r["log_date"], r["title"], r["content"] or "", r["hours"], r["category"] or ""])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=worklogs_export.csv"},
    )
