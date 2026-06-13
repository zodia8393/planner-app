import math

from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import datetime
from common.utils import clamp_text, fix_mojibake, safe_int, validate_date_str

PER_PAGE_DEFAULT = 20

router = APIRouter()


@router.get("/memos", response_class=HTMLResponse)
async def memos_page(request: Request, category_id: str = None,
                     page: int = Query(1, ge=1),
                     per_page: int = Query(PER_PAGE_DEFAULT, ge=1, le=100)):
    S = request.app.state
    pid = S.get_profile_id(request)
    cat_id_int = safe_int(category_id)
    with S.get_db() as conn:
        params: list = [pid]
        where_extra = ""
        if cat_id_int is not None:
            where_extra = " AND m.category_id = ?"
            params.append(cat_id_int)

        # Total count for pagination
        total = conn.execute(f"""
            SELECT COUNT(*) FROM memos m WHERE m.profile_id = ?{where_extra}
        """, params).fetchone()[0]

        total_pages = max(1, math.ceil(total / per_page))
        if page > total_pages:
            page = total_pages
        offset = (page - 1) * per_page

        memos = conn.execute(f"""
            SELECT m.*, c.name as category_name, c.color as category_color
            FROM memos m LEFT JOIN categories c ON m.category_id = c.id
            WHERE m.profile_id = ?{where_extra}
            ORDER BY m.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [per_page, offset]).fetchall()
        categories = S.get_categories(conn, pid)

    # Build filter query string for pagination links
    qs_parts = []
    if cat_id_int is not None:
        qs_parts.append(f"category_id={cat_id_int}")
    if per_page != PER_PAGE_DEFAULT:
        qs_parts.append(f"per_page={per_page}")
    filter_qs = "&".join(qs_parts)

    return S.render(request, "memos.html", {
        "page": "memos",
        "memos": [dict(m) for m in memos],
        "categories": [dict(c) for c in categories],
        "current_category_id": cat_id_int,
        "pg_page": page,
        "pg_per_page": per_page,
        "pg_total": total,
        "pg_total_pages": total_pages,
        "pg_has_next": page < total_pages,
        "pg_has_prev": page > 1,
        "pg_filter_qs": filter_qs,
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
    cat_id = safe_int(category_id)
    # 날짜가 지정되면 해당 날짜 + 현재 시각, 미지정이면 현재 datetime
    ts = None
    validated_date = validate_date_str(created_at.strip()) if created_at else None
    if validated_date:
        now = datetime.now()
        ts = f"{validated_date} {now.strftime('%H:%M:%S')}"
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
            raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다")
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
    cat_id = safe_int(category_id)
    # 날짜가 변경되면 해당 날짜로 created_at 업데이트 (시각은 기존 유지)
    ts = None
    validated_date = validate_date_str(created_at.strip()) if created_at else None
    if validated_date:
        ts = f"{validated_date} 00:00:00"
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
