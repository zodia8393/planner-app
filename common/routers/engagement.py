"""Engagement router — onboarding, morning brief, PWA, visit tracking, review prompt, QR code."""

import json
from datetime import date, timedelta

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()


# ── Onboarding Checklist API ──

@router.get("/api/onboarding")
async def get_onboarding(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        row = conn.execute("SELECT * FROM onboarding_progress WHERE profile_id=?", (pid,)).fetchone()
        if not row:
            conn.execute("INSERT INTO onboarding_progress (profile_id) VALUES (?)", (pid,))
            return JSONResponse({"step1": False, "step2": False, "step3": False, "step4": False, "dismissed": False})
        return JSONResponse({
            "step1": bool(row["step1_done"]), "step2": bool(row["step2_done"]),
            "step3": bool(row["step3_done"]), "step4": bool(row["step4_done"]),
            "dismissed": bool(row["dismissed"]),
        })


@router.post("/api/onboarding/step/{step}")
async def complete_onboarding_step(request: Request, step: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    _STEP_COLS = {1: "step1_done", 2: "step2_done", 3: "step3_done", 4: "step4_done"}
    col = _STEP_COLS.get(step)
    if not col:
        raise HTTPException(400)
    with S.get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO onboarding_progress (profile_id) VALUES (?)", (pid,))
        conn.execute(f"UPDATE onboarding_progress SET {col}=1 WHERE profile_id=?", (pid,))
    return JSONResponse({"ok": True})


@router.post("/api/onboarding/dismiss")
async def dismiss_onboarding(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO onboarding_progress (profile_id) VALUES (?)", (pid,))
        conn.execute("UPDATE onboarding_progress SET dismissed=1 WHERE profile_id=?", (pid,))
    return JSONResponse({"ok": True})


# ── Morning Brief API ──

@router.get("/api/morning-brief")
async def morning_brief(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    today_str = date.today().isoformat()
    with S.get_db() as conn:
        todo_count = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE profile_id=? AND due_date<=? AND completed=0", (pid, today_str)
        ).fetchone()[0]
        event_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE profile_id=? AND date(start_time)=?", (pid, today_str)
        ).fetchone()[0]
        habits_total = conn.execute(
            "SELECT COUNT(*) FROM habits WHERE profile_id=? AND archived=0", (pid,)
        ).fetchone()[0]
        habits_done = conn.execute(
            "SELECT COUNT(*) FROM habit_logs WHERE profile_id=? AND log_date=?", (pid, today_str)
        ).fetchone()[0]
    return JSONResponse({
        "date": today_str,
        "todos_pending": todo_count,
        "events_today": event_count,
        "habits_total": habits_total,
        "habits_done": habits_done,
        "message": f"오늘 할 일 {todo_count}개, 일정 {event_count}개가 있습니다.",
    })


@router.post("/api/morning-brief/settings")
async def save_morning_brief_settings(request: Request, enabled: int = Form(0), hour: int = Form(8), minute: int = Form(0)):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO morning_brief_settings (profile_id, enabled, hour, minute) VALUES (?,?,?,?)",
            (pid, enabled, max(0, min(23, hour)), max(0, min(59, minute))),
        )
    return JSONResponse({"ok": True})


@router.get("/api/morning-brief/settings")
async def get_morning_brief_settings(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        row = conn.execute("SELECT * FROM morning_brief_settings WHERE profile_id=?", (pid,)).fetchone()
    if not row:
        return JSONResponse({"enabled": False, "hour": 8, "minute": 0})
    return JSONResponse({"enabled": bool(row["enabled"]), "hour": row["hour"], "minute": row["minute"]})


# ── PWA Install + Visit Tracking + Review Prompt ──

@router.post("/api/pwa-install-dismissed")
async def pwa_install_dismissed(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    _set_user_setting = getattr(S, "set_user_setting", None)
    with S.get_db() as conn:
        if _set_user_setting:
            _set_user_setting(conn, str(pid), "pwa_install_dismissed", "1")
        else:
            conn.execute(
                "INSERT OR REPLACE INTO user_settings (profile_id, key, value) VALUES (?, ?, ?)",
                (str(pid), "pwa_install_dismissed", "1"),
            )
    return JSONResponse({"ok": True})


@router.post("/api/track-visit")
async def track_visit(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    today_str = date.today().isoformat()
    with S.get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO app_visits (profile_id, visit_date) VALUES (?,?)", (pid, today_str))
    return JSONResponse({"ok": True})


@router.get("/api/review-prompt")
async def check_review_prompt(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    today = date.today()
    with S.get_db() as conn:
        snoozed = conn.execute(
            "SELECT value FROM user_settings WHERE profile_id=? AND key='review_snoozed_until'", (str(pid),)
        ).fetchone()
        if snoozed and snoozed["value"] and snoozed["value"] > today.isoformat():
            return JSONResponse({"show": False})
        reviewed = conn.execute(
            "SELECT value FROM user_settings WHERE profile_id=? AND key='review_done'", (str(pid),)
        ).fetchone()
        if reviewed:
            return JSONResponse({"show": False})
        streak = 0
        for i in range(7):
            d = (today - timedelta(days=i)).isoformat()
            exists = conn.execute(
                "SELECT 1 FROM app_visits WHERE profile_id=? AND visit_date=?", (pid, d)
            ).fetchone()
            if exists:
                streak += 1
            else:
                break
    return JSONResponse({"show": streak >= 7})


@router.post("/api/review-prompt/dismiss")
async def dismiss_review_prompt(request: Request, action: str = Form("snooze")):
    S = request.app.state
    pid = S.get_profile_id(request)
    _set_user_setting = getattr(S, "set_user_setting", None)
    with S.get_db() as conn:
        if action == "done":
            if _set_user_setting:
                _set_user_setting(conn, str(pid), "review_done", "1")
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO user_settings (profile_id, key, value) VALUES (?, ?, ?)",
                    (str(pid), "review_done", "1"),
                )
        else:
            snooze_until = (date.today() + timedelta(days=30)).isoformat()
            if _set_user_setting:
                _set_user_setting(conn, str(pid), "review_snoozed_until", snooze_until)
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO user_settings (profile_id, key, value) VALUES (?, ?, ?)",
                    (str(pid), "review_snoozed_until", snooze_until),
                )
    return JSONResponse({"ok": True})


# ── QR Code Access ──

@router.get("/api/qr-code")
async def qr_code_api(request: Request):
    import qrcode
    import io as _io
    import base64
    host = request.headers.get("host", "localhost:8002")
    scheme = "https" if request.url.scheme == "https" or "fly.dev" in host else "http"
    url = f"{scheme}://{host}"
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return JSONResponse({"qr_base64": b64, "url": url})
