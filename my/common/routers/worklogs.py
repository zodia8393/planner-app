import math
import re as _re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from common.image import _check_image_magic
from common.utils import clamp_text, fix_mojibake, validate_date_str, safe_int

PER_PAGE_DEFAULT = 20

router = APIRouter()


@router.get("/worklogs", response_class=HTMLResponse)
async def worklogs_page(request: Request,
                        date_param: str = Query(None, alias="date"),
                        start: str = Query(None),
                        end: str = Query(None),
                        category_id: str = Query(None, alias="cat"),
                        page: int = Query(1, ge=1),
                        per_page: int = Query(PER_PAGE_DEFAULT, ge=1, le=100)):
    S = request.app.state
    pid = S.get_profile_id(request)
    today = date.today()

    with S.get_db() as conn:
        categories = S.get_categories(conn, pid)
        cats_list = [dict(c) for c in categories]

        # Range mode: start & end both provided, or default 7-day view
        start_date = validate_date_str(start) if start else None
        end_date = validate_date_str(end) if end else None
        explicit_range = bool(start_date and end_date)

        # 날짜 파라미터 없으면 이번 주(월~일) 기본 표시
        if not date_param and not explicit_range:
            monday = today - timedelta(days=today.weekday())
            sunday = monday + timedelta(days=6)
            start_date = monday.isoformat()
            end_date = sunday.isoformat()
        range_mode = bool(start_date and end_date)

        if range_mode:
            # Ensure start <= end
            if start_date > end_date:
                start_date, end_date = end_date, start_date

            cat_filter = safe_int(category_id)
            count_where = "wl.profile_id = ? AND wl.log_date BETWEEN ? AND ?"
            count_params: list = [pid, start_date, end_date]
            if cat_filter:
                count_where += " AND wl.category_id = ?"
                count_params.append(cat_filter)

            # Total count + hours for pagination
            agg = conn.execute(f"""
                SELECT COUNT(*) as cnt, COALESCE(SUM(wl.hours), 0) as total_h
                FROM work_logs wl WHERE {count_where}
            """, count_params).fetchone()
            total = agg["cnt"]
            total_hours = agg["total_h"]

            total_pages = max(1, math.ceil(total / per_page))
            if page > total_pages:
                page = total_pages
            offset = (page - 1) * per_page

            logs = conn.execute(f"""
                SELECT wl.*, c.name as category_name, c.color as category_color
                FROM work_logs wl LEFT JOIN categories c ON wl.category_id = c.id
                WHERE {count_where}
                ORDER BY wl.log_date DESC, wl.created_at DESC
                LIMIT ? OFFSET ?
            """, count_params + [per_page, offset]).fetchall()

            logs_list = [dict(l) for l in logs]

            # Group by date
            logs_by_date: dict = {}
            for log in logs_list:
                d = log.get("log_date", "")
                logs_by_date.setdefault(d, []).append(log)

            # For single-date nav, use today as default
            current_date = today.isoformat()
            current_dt = today
        else:
            if date_param:
                current_date = validate_date_str(date_param) or today.isoformat()
            else:
                current_date = today.isoformat()

            try:
                current_dt = datetime.strptime(current_date, "%Y-%m-%d").date()
            except ValueError:
                current_dt = today

            # Total count + hours for pagination
            agg = conn.execute("""
                SELECT COUNT(*) as cnt, COALESCE(SUM(wl.hours), 0) as total_h
                FROM work_logs wl WHERE wl.profile_id = ? AND wl.log_date = ?
            """, (pid, current_date)).fetchone()
            total = agg["cnt"]
            total_hours = agg["total_h"]

            total_pages = max(1, math.ceil(total / per_page))
            if page > total_pages:
                page = total_pages
            offset = (page - 1) * per_page

            logs = conn.execute("""
                SELECT wl.*, c.name as category_name, c.color as category_color
                FROM work_logs wl LEFT JOIN categories c ON wl.category_id = c.id
                WHERE wl.profile_id = ? AND wl.log_date = ?
                ORDER BY wl.created_at DESC
                LIMIT ? OFFSET ?
            """, (pid, current_date, per_page, offset)).fetchall()

            logs_list = [dict(l) for l in logs]
            logs_by_date = {}

    prev_date = (current_dt - timedelta(days=1)).isoformat()
    next_date = (current_dt + timedelta(days=1)).isoformat()
    is_today = current_dt == today

    # 주간 뷰: 기본 접근이거나, start/end가 월~일 7일 범위일 때
    week_mode = False
    if range_mode and not date_param:
        if not explicit_range:
            week_mode = True
        else:
            try:
                _sd = datetime.strptime(start_date, "%Y-%m-%d").date()
                _ed = datetime.strptime(end_date, "%Y-%m-%d").date()
                week_mode = (_ed - _sd).days == 6 and _sd.weekday() == 0
            except ValueError:
                pass

    # 주간 네비게이션 날짜 계산 (항상 월~일 단위)
    if range_mode and start_date and end_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            sd = today - timedelta(days=today.weekday())
        prev_week_start = (sd - timedelta(days=7)).isoformat()
        prev_week_end = (sd - timedelta(days=1)).isoformat()
        next_week_start = (sd + timedelta(days=7)).isoformat()
        next_week_end = (sd + timedelta(days=13)).isoformat()
    else:
        prev_week_start = prev_week_end = next_week_start = next_week_end = ""

    # Build filter query string for pagination links
    qs_parts = []
    if date_param:
        qs_parts.append(f"date={date_param}")
    if start_date and explicit_range:
        qs_parts.append(f"start={start_date}")
    if end_date and explicit_range:
        qs_parts.append(f"end={end_date}")
    if category_id:
        qs_parts.append(f"cat={category_id}")
    if per_page != PER_PAGE_DEFAULT:
        qs_parts.append(f"per_page={per_page}")
    filter_qs = "&".join(qs_parts)

    return S.render(request, "worklogs.html", {
        "page": "worklogs",
        "logs": logs_list,
        "categories": cats_list,
        "current_date": current_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "is_today": is_today,
        "total_hours": round(total_hours, 1),
        "range_mode": range_mode,
        "week_mode": week_mode,
        "start_date": start_date or "",
        "end_date": end_date or "",
        "logs_by_date": logs_by_date,
        "selected_category": category_id or "",
        "prev_week_start": prev_week_start,
        "prev_week_end": prev_week_end,
        "next_week_start": next_week_start,
        "next_week_end": next_week_end,
        "pg_page": page,
        "pg_per_page": per_page,
        "pg_total": total,
        "pg_total_pages": total_pages,
        "pg_has_next": page < total_pages,
        "pg_has_prev": page > 1,
        "pg_filter_qs": filter_qs,
    })


@router.post("/worklogs", response_class=HTMLResponse)
async def create_worklog(request: Request,
                         title: str = Form(""),
                         content: str = Form(""),
                         hours: float = Form(0),
                         category_id: str = Form(""),
                         log_date: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    if not title:
        return S.redirect(request, f"/worklogs?date={log_date or date.today().isoformat()}")
    content = clamp_text(fix_mojibake(content), 5000)
    hours = max(0.0, min(24.0, hours))
    cat_id = safe_int(category_id)
    log_date = validate_date_str(log_date) or date.today().isoformat()
    with S.get_db() as conn:
        conn.execute("""
            INSERT INTO work_logs (profile_id, log_date, title, content, hours, category_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (pid, log_date, title, content, hours, cat_id))
    return S.redirect(request, f"/worklogs?date={log_date}")


@router.post("/worklogs/upload-image")
async def upload_worklog_image(request: Request, file: UploadFile = File(...)):
    S = request.app.state
    pid = S.get_profile_id(request)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(400, detail="파일 크기가 10MB를 초과합니다")

    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        raise HTTPException(400, detail="지원하지 않는 이미지 형식입니다")

    if not _check_image_magic(content, ext):
        raise HTTPException(400, detail="파일 내용이 이미지가 아닙니다")

    filename = f"wl_{pid}_{uuid.uuid4().hex[:8]}{ext}"
    (S.worklog_img_dir / filename).write_bytes(content)

    return JSONResponse({"url": f"/worklog-images/{filename}"})


@router.get("/worklogs/{log_id}/edit", response_class=HTMLResponse)
async def edit_worklog_form(request: Request, log_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        log = conn.execute(
            "SELECT * FROM work_logs WHERE id=? AND profile_id=?", (log_id, pid)
        ).fetchone()
        if not log:
            return HTMLResponse("")
        categories = S.get_categories(conn, pid)
    return S.templates.TemplateResponse(request, "partials/worklog_edit_form.html", {
        "log": dict(log),
        "categories": [dict(c) for c in categories],
    })


@router.put("/worklogs/{log_id}", response_class=HTMLResponse)
async def update_worklog(request: Request, log_id: int,
                         title: str = Form(""),
                         content: str = Form(""),
                         hours: float = Form(0),
                         category_id: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    content = clamp_text(fix_mojibake(content), 5000)
    hours = max(0.0, min(24.0, hours))
    cat_id = safe_int(category_id)
    with S.get_db() as conn:
        log = conn.execute("SELECT log_date FROM work_logs WHERE id=? AND profile_id=?", (log_id, pid)).fetchone()
        if not log:
            return S.redirect(request, "/worklogs")
        conn.execute("""
            UPDATE work_logs SET title=?, content=?, hours=?, category_id=?,
                   updated_at=datetime('now','localtime')
            WHERE id=? AND profile_id=?
        """, (title, content, hours, cat_id, log_id, pid))
        log_date = log["log_date"]
    return S.redirect(request, f"/worklogs?date={log_date}")


@router.delete("/worklogs/{log_id}", response_class=HTMLResponse)
async def delete_worklog(request: Request, log_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        row = conn.execute("SELECT content FROM work_logs WHERE id=? AND profile_id=?", (log_id, pid)).fetchone()
        if row and row["content"]:
            for img_path in _re.findall(r'!\[[^\]]*\]\((/worklog-images/([^)]+))\)', row["content"]):
                try:
                    img_file = S.worklog_img_dir / img_path[1]
                    if img_file.is_file():
                        img_file.unlink()
                except OSError:
                    pass
        conn.execute("DELETE FROM work_logs WHERE id=? AND profile_id=?", (log_id, pid))
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return S.redirect(request, "/worklogs")
