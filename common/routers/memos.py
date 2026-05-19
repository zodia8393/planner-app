from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from typing import Optional
from common.utils import clamp_text, fix_mojibake

router = APIRouter()


@router.get("/memos", response_class=HTMLResponse)
async def memos_page(request: Request, category_id: Optional[int] = None):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        params: list = [pid]
        where_extra = ""
        if category_id is not None:
            where_extra = " AND m.category_id = ?"
            params.append(category_id)
        memos = conn.execute(f"""
            SELECT m.*, c.name as category_name, c.color as category_color
            FROM memos m LEFT JOIN categories c ON m.category_id = c.id
            WHERE m.profile_id = ?{where_extra}
            ORDER BY m.created_at DESC
        """, params).fetchall()
        categories = S.get_categories(conn, pid)
    return S.render(request, "memos.html", {
        "page": "memos",
        "memos": [dict(m) for m in memos],
        "categories": [dict(c) for c in categories],
        "current_category_id": category_id,
    })


@router.post("/memos", response_class=HTMLResponse)
async def create_memo(request: Request,
                      content: str = Form(...),
                      title: str = Form(""),
                      category_id: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    content = clamp_text(fix_mojibake(content), 5000).strip()
    title = clamp_text(fix_mojibake(title), 200)
    if not content:
        return S.redirect(request, "/memos")
    author = S.get_profile_name(request)
    cat_id = int(category_id) if category_id else None
    with S.get_db() as conn:
        conn.execute(
            "INSERT INTO memos (author, content, title, category_id, profile_id) VALUES (?, ?, ?, ?, ?)",
            (author, content, title, cat_id, pid),
        )
    return S.redirect(request, "/memos")


@router.get("/memos/{memo_id}/view", response_class=HTMLResponse)
async def view_memo_card(request: Request, memo_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        memo = conn.execute(
            "SELECT m.*, c.name as category_name, c.color as category_color "
            "FROM memos m LEFT JOIN categories c ON m.category_id = c.id WHERE m.id=? AND m.profile_id=?",
            (memo_id, pid),
        ).fetchone()
        if not memo:
            raise HTTPException(404)
    return S.templates.TemplateResponse(request, "partials/memo_card.html", {"memo": dict(memo)})


@router.get("/memos/{memo_id}/edit", response_class=HTMLResponse)
async def edit_memo_form(request: Request, memo_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        memo = conn.execute(
            "SELECT m.*, c.name as category_name, c.color as category_color "
            "FROM memos m LEFT JOIN categories c ON m.category_id = c.id WHERE m.id=? AND m.profile_id=?",
            (memo_id, pid),
        ).fetchone()
        if not memo:
            raise HTTPException(404)
        categories = S.get_categories(conn, pid)
    return S.templates.TemplateResponse(request, "partials/memo_edit_form.html", {
        "memo": dict(memo), "categories": [dict(c) for c in categories],
    })


@router.put("/memos/{memo_id}", response_class=HTMLResponse)
async def update_memo(request: Request, memo_id: int,
                      title: str = Form(""), content: str = Form(...),
                      category_id: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    content = clamp_text(fix_mojibake(content), 5000)
    cat_id = int(category_id) if category_id else None
    with S.get_db() as conn:
        conn.execute(
            "UPDATE memos SET title=?, content=?, category_id=? WHERE id=? AND profile_id=?",
            (title, content, cat_id, memo_id, pid),
        )
        if request.headers.get("HX-Request"):
            memo = conn.execute(
                "SELECT m.*, c.name as category_name, c.color as category_color "
                "FROM memos m LEFT JOIN categories c ON m.category_id = c.id WHERE m.id=? AND m.profile_id=?",
                (memo_id, pid),
            ).fetchone()
            if memo:
                return S.templates.TemplateResponse(request, "partials/memo_card.html", {"memo": dict(memo)})
    return S.redirect(request, "/memos")


@router.delete("/memos/{memo_id}", response_class=HTMLResponse)
async def delete_memo(request: Request, memo_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM memos WHERE id=? AND profile_id=?", (memo_id, pid))
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return S.redirect(request, "/memos")
