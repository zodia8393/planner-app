from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import datetime
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
                      content: str = Form(""),
                      title: str = Form(""),
                      category_id: str = Form(""),
                      created_at: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    content = clamp_text(fix_mojibake(content), 5000).strip()
    title = clamp_text(fix_mojibake(title), 200)
    if not content:
        return S.redirect(request, "/memos")
    author = S.get_profile_name(request)
    cat_id = int(category_id) if category_id else None
    # 날짜가 지정되면 해당 날짜 + 현재 시각, 미지정이면 현재 datetime
    ts = None
    if created_at.strip():
        try:
            now = datetime.now()
            ts = f"{created_at.strip()} {now.strftime('%H:%M:%S')}"
        except Exception:
            ts = None
    with S.get_db() as conn:
        if ts:
            conn.execute(
                "INSERT INTO memos (author, content, title, category_id, profile_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (author, content, title, cat_id, pid, ts),
            )
        else:
            conn.execute(
                "INSERT INTO memos (author, content, title, category_id, profile_id) VALUES (?, ?, ?, ?, ?)",
                (author, content, title, cat_id, pid),
            )
    S.event_bus.emit("memo", {"action": "created", "title": title})
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
            return HTMLResponse("")
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
            return HTMLResponse("")
        categories = S.get_categories(conn, pid)
    return S.templates.TemplateResponse(request, "partials/memo_edit_form.html", {
        "memo": dict(memo), "categories": [dict(c) for c in categories],
    })


@router.put("/memos/{memo_id}", response_class=HTMLResponse)
async def update_memo(request: Request, memo_id: int,
                      title: str = Form(""), content: str = Form(""),
                      category_id: str = Form(""),
                      created_at: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    content = clamp_text(fix_mojibake(content), 5000)
    cat_id = int(category_id) if category_id else None
    # 날짜가 변경되면 해당 날짜로 created_at 업데이트 (시각은 기존 유지)
    ts = None
    if created_at.strip():
        try:
            ts = f"{created_at.strip()} 00:00:00"
        except Exception:
            ts = None
    with S.get_db() as conn:
        if ts:
            # 기존 시각 부분 보존: 날짜만 교체
            existing = conn.execute(
                "SELECT created_at FROM memos WHERE id=? AND profile_id=?",
                (memo_id, pid),
            ).fetchone()
            if existing and existing["created_at"]:
                old_time = existing["created_at"][11:] if len(existing["created_at"]) > 10 else "00:00:00"
                ts = f"{created_at.strip()} {old_time}"
            conn.execute(
                "UPDATE memos SET title=?, content=?, category_id=?, created_at=? WHERE id=? AND profile_id=?",
                (title, content, cat_id, ts, memo_id, pid),
            )
        else:
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
