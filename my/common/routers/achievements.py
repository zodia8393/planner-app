"""Achievements router — /achievements, /api/achievements/check."""

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from common.achievements import (
    check_achievements, get_earned_achievements, get_completion_streak,
    get_today_completed_count, get_total_completed, ACHIEVEMENT_DEFS,
)

router = APIRouter()


@router.get("/achievements", response_class=HTMLResponse)
async def achievements_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        try:
            check_achievements(conn, pid)
            achievements = get_earned_achievements(conn, pid)
            streak = get_completion_streak(conn, pid)
            total = get_total_completed(conn, pid)
            earned_count = sum(1 for a in achievements if a["earned"])
        except Exception:
            achievements = []
            streak = 0
            total = 0
            earned_count = 0
    return S.render(request, "achievements.html", {
        "page": "achievements",
        "achievements": achievements,
        "streak": streak,
        "total_completed": total,
        "earned_count": earned_count,
        "total_count": len(achievements) if achievements else len(ACHIEVEMENT_DEFS),
    })


@router.get("/api/achievements/check", response_class=JSONResponse)
async def api_check_achievements(request: Request):
    """Called after todo toggle to check for new achievements."""
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        try:
            newly = check_achievements(conn, pid)
            streak = get_completion_streak(conn, pid)
            today_count = get_today_completed_count(conn, pid)
            today_total = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE profile_id=? AND due_date=?",
                (pid, date.today().isoformat()),
            ).fetchone()[0] or 0
        except Exception:
            newly = []
            streak = 0
            today_count = 0
            today_total = 0
    return JSONResponse({
        "new_achievements": [{"icon": a["icon"], "title": a["title"], "desc": a["desc"]} for a in newly],
        "streak": streak,
        "today_completed": today_count,
        "today_total": today_total,
    })
