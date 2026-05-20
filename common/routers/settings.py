import io
import os
import shutil
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import StreamingResponse
from common.utils import clamp_text, fix_mojibake

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        categories = S.get_categories(conn, pid)
        budgets = conn.execute(
            "SELECT category_id, weekly_hours FROM time_budgets WHERE profile_id=?", (pid,)
        ).fetchall()
        profile = None
        if pid:
            profile_table = getattr(S, "profile_table", "work_profiles")
            profile = conn.execute(f"SELECT * FROM {profile_table} WHERE id=?", (pid,)).fetchone()
        gcal_row = None
        try:
            gcal_row = conn.execute(
                "SELECT * FROM gcal_tokens WHERE profile_id=?", (pid,)
            ).fetchone()
        except Exception:
            pass
    budget_map = {b["category_id"]: b["weekly_hours"] for b in budgets}
    time_budget_cats = [dict(c) | {"budget_hours": budget_map.get(c["id"], 0)} for c in categories]
    gcal_client_id = getattr(S, "gcal_client_id", "") or os.environ.get("GCAL_CLIENT_ID", "")
    ctx = {
        "page": "settings",
        "categories": [dict(c) for c in categories],
        "time_budget_cats": time_budget_cats,
        "gcal_configured": bool(gcal_client_id),
        "gcal_connected": gcal_row is not None,
        "gcal_calendar_id": gcal_row["calendar_id"] if gcal_row else "primary",
    }
    if profile:
        ctx["profile"] = dict(profile)
    return S.render(request, "settings.html", ctx)


@router.post("/settings/categories", response_class=HTMLResponse)
async def create_category(request: Request,
                          name: str = Form(...),
                          color: str = Form("#6366f1")):
    S = request.app.state
    pid = S.get_profile_id(request)
    name = clamp_text(fix_mojibake(name), 50)
    with S.get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM categories WHERE profile_id=?", (pid,)).fetchone()[0]
        try:
            conn.execute(
                "INSERT INTO categories (profile_id, name, color, sort_order) VALUES (?, ?, ?, ?)",
                (pid, name, color, max_order + 1),
            )
        except sqlite3.IntegrityError:
            pass  # duplicate name
    return S.redirect(request, "/settings")


@router.delete("/settings/categories/{cat_id}", response_class=HTMLResponse)
async def delete_category(request: Request, cat_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM categories WHERE id=? AND profile_id=?", (cat_id, pid))
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return S.redirect(request, "/settings")


@router.get("/settings/time-budgets", response_class=HTMLResponse)
async def time_budgets_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        categories = S.get_categories(conn, pid)
        budgets = conn.execute(
            "SELECT category_id, weekly_hours FROM time_budgets WHERE profile_id=?", (pid,)
        ).fetchall()
        profile = None
        if pid:
            profile_table = getattr(S, "profile_table", "work_profiles")
            profile = conn.execute(f"SELECT * FROM {profile_table} WHERE id=?", (pid,)).fetchone()
    budget_map = {b["category_id"]: b["weekly_hours"] for b in budgets}
    cats = [dict(c) | {"budget_hours": budget_map.get(c["id"], 0)} for c in categories]
    ctx = {
        "page": "settings",
        "categories": [dict(c) for c in categories],
        "time_budget_cats": cats,
        "show_time_budgets": True,
    }
    if profile:
        ctx["profile"] = dict(profile)
    return S.render(request, "settings.html", ctx)


@router.post("/settings/time-budgets", response_class=HTMLResponse)
async def save_time_budgets(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    form = await request.form()
    cat_ids = form.getlist("category_id")
    hours_list = form.getlist("weekly_hours")
    with S.get_db() as conn:
        conn.execute("DELETE FROM time_budgets WHERE profile_id=?", (pid,))
        for cid, hrs in zip(cat_ids, hours_list):
            h = float(hrs or 0)
            if h > 0:
                conn.execute(
                    "INSERT INTO time_budgets (profile_id, category_id, weekly_hours) VALUES (?, ?, ?)",
                    (pid, int(cid), h),
                )
    return S.redirect(request, "/settings/time-budgets")


@router.get("/settings/backup")
async def download_backup(request: Request):
    """Download full data backup as ZIP."""
    S = request.app.state
    S.get_profile_id(request)
    try:
        with S.get_db() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    data_dir = S.base_dir / "data"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(data_dir):
            dirs[:] = [d for d in dirs if d != "backup_before_restore"]
            for f in files:
                fp = Path(root) / f
                if fp.suffix in ('.db-wal', '.db-shm'):
                    continue
                arcname = str(fp.relative_to(data_dir))
                zf.write(fp, arcname)
    buf.seek(0)
    today_str = date.today().isoformat()
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=backup_{today_str}.zip"},
    )


@router.post("/settings/restore")
async def restore_backup(request: Request, file: UploadFile = File(...)):
    """Restore data from uploaded ZIP backup."""
    S = request.app.state
    S.get_profile_id(request)
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(400, "ZIP 파일만 지원합니다")
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(400, "파일이 너무 큽니다 (100MB 제한)")
    buf = io.BytesIO(content)
    try:
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            if not any(n.endswith('.db') for n in names):
                raise HTTPException(400, "유효한 백업 파일이 아닙니다")
            for name in names:
                if name.startswith('/') or '..' in name:
                    raise HTTPException(400, "유효한 백업 파일이 아닙니다")
            data_dir = S.base_dir / "data"
            backup_dir = data_dir / "backup_before_restore"
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            backup_dir.mkdir(exist_ok=True)
            for item in data_dir.iterdir():
                if item.name == "backup_before_restore":
                    continue
                dest = backup_dir / item.name
                if item.is_file():
                    shutil.copy2(item, dest)
                elif item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
            zf.extractall(str(data_dir))
    except zipfile.BadZipFile:
        raise HTTPException(400, "유효한 ZIP 파일이 아닙니다")
    return RedirectResponse("/settings", status_code=303)
