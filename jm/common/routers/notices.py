from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from common.utils import clamp_text, fix_mojibake

router = APIRouter()


@router.get("/notices", response_class=HTMLResponse)
async def notices_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        notices = conn.execute("""
            SELECT * FROM notices
            WHERE profile_id = ?
            ORDER BY pinned DESC, created_at DESC
        """, (pid,)).fetchall()
    return S.render(request, "notices.html", {
        "page": "notices",
        "notices": [dict(n) for n in notices],
    })


@router.post("/notices", response_class=HTMLResponse)
async def create_notice(request: Request,
                        title: str = Form(""),
                        content: str = Form(""),
                        priority: int = Form(0)):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    if not title:
        return S.redirect(request, "/notices")
    content = clamp_text(fix_mojibake(content), 5000)
    priority = max(0, min(1, priority))
    with S.get_db() as conn:
        extra_cols = ""
        extra_vals = ""
        params = [pid, title, content, priority]
        if hasattr(S, "get_network_group"):
            extra_cols = ", network_group"
            extra_vals = ", ?"
            params.append(S.get_network_group(request))
        conn.execute(f"""
            INSERT INTO notices (profile_id, title, content, priority{extra_cols})
            VALUES (?, ?, ?, ?{extra_vals})
        """, params)
        S.audit_log(conn, "notice", conn.execute("SELECT last_insert_rowid()").fetchone()[0],
                    "create", {"title": title}, str(pid))
    S.event_bus.emit("notice", {"action": "created", "title": title})
    return S.redirect(request, "/notices")


@router.get("/notices/{notice_id}/edit", response_class=HTMLResponse)
async def edit_notice_form(request: Request, notice_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        notice = conn.execute(
            "SELECT * FROM notices WHERE id=? AND profile_id=?",
            (notice_id, pid),
        ).fetchone()
        if not notice:
            return HTMLResponse("")
    return S.templates.TemplateResponse(request, "partials/notice_edit_form.html", {
        "notice": dict(notice),
    })


@router.put("/notices/{notice_id}", response_class=HTMLResponse)
async def update_notice(request: Request, notice_id: int,
                        title: str = Form(""),
                        content: str = Form(""),
                        priority: int = Form(0)):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    content = clamp_text(fix_mojibake(content), 5000)
    priority = max(0, min(1, priority))
    with S.get_db() as conn:
        conn.execute("""
            UPDATE notices SET title=?, content=?, priority=?,
                   updated_at=datetime('now','localtime')
            WHERE id=? AND profile_id=?
        """, (title, content, priority, notice_id, pid))
    return S.redirect(request, "/notices")


@router.delete("/notices/{notice_id}", response_class=HTMLResponse)
async def delete_notice(request: Request, notice_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        notice = conn.execute(
            "SELECT profile_id FROM notices WHERE id=? AND profile_id=?",
            (notice_id, pid),
        ).fetchone()
        if not notice:
            if request.headers.get("HX-Request"):
                return HTMLResponse("")
            return S.redirect(request, "/notices")
        conn.execute("DELETE FROM notices WHERE id=? AND profile_id=?", (notice_id, pid))
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return S.redirect(request, "/notices")


@router.post("/notices/{notice_id}/pin", response_class=HTMLResponse)
async def toggle_pin_notice(request: Request, notice_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        notice = conn.execute(
            "SELECT * FROM notices WHERE id=? AND profile_id=?",
            (notice_id, pid),
        ).fetchone()
        if not notice:
            return S.redirect(request, "/notices")
        new_pinned = 0 if notice["pinned"] else 1
        conn.execute("UPDATE notices SET pinned=? WHERE id=?", (new_pinned, notice_id))
    return S.redirect(request, "/notices")
