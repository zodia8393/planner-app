import re as _re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from common.image import _check_image_magic
from common.utils import clamp_text, fix_mojibake, validate_date_str

router = APIRouter()


@router.get("/worklogs", response_class=HTMLResponse)
async def worklogs_page(request: Request,
                        date_param: str = Query(None, alias="date"),
                        start: str = Query(None),
                        end: str = Query(None),
                        category_id: str = Query(None, alias="cat")):
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

            cat_filter = int(category_id) if category_id else None
            if cat_filter:
                logs = conn.execute("""
                    SELECT wl.*, c.name as category_name, c.color as category_color
                    FROM work_logs wl LEFT JOIN categories c ON wl.category_id = c.id
                    WHERE wl.profile_id = ? AND wl.log_date BETWEEN ? AND ? AND wl.category_id = ?
                    ORDER BY wl.log_date DESC, wl.created_at DESC
                """, (pid, start_date, end_date, cat_filter)).fetchall()
            else:
                logs = conn.execute("""
                    SELECT wl.*, c.name as category_name, c.color as category_color
                    FROM work_logs wl LEFT JOIN categories c ON wl.category_id = c.id
                    WHERE wl.profile_id = ? AND wl.log_date BETWEEN ? AND ?
                    ORDER BY wl.log_date DESC, wl.created_at DESC
                """, (pid, start_date, end_date)).fetchall()

            logs_list = [dict(l) for l in logs]
            total_hours = sum(l.get("hours", 0) or 0 for l in logs_list)

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

            logs = conn.execute("""
                SELECT wl.*, c.name as category_name, c.color as category_color
                FROM work_logs wl LEFT JOIN categories c ON wl.category_id = c.id
                WHERE wl.profile_id = ? AND wl.log_date = ?
                ORDER BY wl.created_at DESC
            """, (pid, current_date)).fetchall()

            logs_list = [dict(l) for l in logs]
            total_hours = sum(l.get("hours", 0) or 0 for l in logs_list)
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
    cat_id = int(category_id) if category_id else None
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
            raise HTTPException(status_code=404, detail="업무일지를 찾을 수 없습니다")
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
    cat_id = int(category_id) if category_id else None
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
