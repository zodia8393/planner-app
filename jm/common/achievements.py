"""Achievement system for planner apps — gamification engine.

Checks are idempotent: calling check_achievements() multiple times
won't duplicate already-earned achievements.
"""

import json
from datetime import date, timedelta


# ── Achievement Definitions ──
# Each has: id, icon, title, description, check function name
ACHIEVEMENT_DEFS = [
    {"id": "first_complete",    "icon": "🌱", "title": "첫 걸음",         "desc": "첫 번째 할일을 완료했어요"},
    {"id": "streak_3",          "icon": "🔥", "title": "3일 연속",        "desc": "3일 연속으로 할일을 완료했어요"},
    {"id": "streak_7",          "icon": "🔥", "title": "7일 연속",        "desc": "7일 연속으로 할일을 완료했어요"},
    {"id": "streak_14",         "icon": "⚡", "title": "2주 연속",        "desc": "14일 연속으로 할일을 완료했어요"},
    {"id": "streak_30",         "icon": "🏔️", "title": "30일 연속",       "desc": "30일 연속으로 할일을 완료했어요"},
    {"id": "streak_100",        "icon": "💎", "title": "100일 연속",      "desc": "100일 연속으로 할일을 완료했어요"},
    {"id": "daily_5",           "icon": "⭐", "title": "오늘의 스타",     "desc": "하루에 5개 할일을 완료했어요"},
    {"id": "daily_10",          "icon": "💯", "title": "완벽한 하루",     "desc": "하루에 10개 할일을 완료했어요"},
    {"id": "total_10",          "icon": "📝", "title": "열 번째 완료",    "desc": "총 10개 할일을 완료했어요"},
    {"id": "total_50",          "icon": "📚", "title": "오십 번째 완료",  "desc": "총 50개 할일을 완료했어요"},
    {"id": "total_100",         "icon": "🌟", "title": "백 번째 완료",    "desc": "총 100개 할일을 완료했어요"},
    {"id": "total_500",         "icon": "🏆", "title": "오백 번째 완료",  "desc": "총 500개 할일을 완료했어요"},
    {"id": "week_100",          "icon": "🎯", "title": "주간 100%",       "desc": "주간 할일을 모두 완료했어요"},
    {"id": "focus_60",          "icon": "⏱️", "title": "집중의 달인",     "desc": "집중 모드로 1시간 이상 기록했어요"},
    {"id": "month_perfect",     "icon": "📅", "title": "완벽한 한 달",    "desc": "한 달간 매일 할일을 완료했어요"},
    {"id": "early_bird",        "icon": "🐦", "title": "얼리버드",        "desc": "오전 9시 전에 할일을 완료했어요"},
    {"id": "night_owl",         "icon": "🦉", "title": "야행성",          "desc": "밤 11시 이후에 할일을 완료했어요"},
    {"id": "category_master",   "icon": "🎨", "title": "카테고리 마스터", "desc": "3개 이상 카테고리에서 할일을 완료했어요"},
]

ACHIEVEMENT_MAP = {a["id"]: a for a in ACHIEVEMENT_DEFS}


def get_earned_achievements(conn, pid: int) -> list[dict]:
    """Return list of earned achievement dicts with metadata."""
    rows = conn.execute(
        "SELECT achievement_id, achieved_at FROM achievements WHERE profile_id=? ORDER BY achieved_at DESC",
        (pid,),
    ).fetchall()
    earned = {}
    for r in rows:
        earned[r["achievement_id"]] = r["achieved_at"]

    result = []
    for a in ACHIEVEMENT_DEFS:
        d = dict(a)
        if a["id"] in earned:
            d["earned"] = True
            d["achieved_at"] = earned[a["id"]]
        else:
            d["earned"] = False
            d["achieved_at"] = None
        result.append(d)
    return result


def get_completion_streak(conn, pid: int) -> int:
    """Calculate current consecutive days with at least one completed todo."""
    today = date.today()
    streak = 0
    d = today
    while True:
        row = conn.execute(
            "SELECT 1 FROM todos WHERE profile_id=? AND completed=1 AND date(completed_at)=? LIMIT 1",
            (pid, d.isoformat()),
        ).fetchone()
        if row:
            streak += 1
            d -= timedelta(days=1)
        else:
            break
    return streak


def get_today_completed_count(conn, pid: int) -> int:
    """Count todos completed today."""
    today_str = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=1 AND date(completed_at)=?",
        (pid, today_str),
    ).fetchone()
    return row[0] or 0


def get_total_completed(conn, pid: int) -> int:
    """Total completed todos ever."""
    row = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=1",
        (pid,),
    ).fetchone()
    return row[0] or 0


def check_achievements(conn, pid: int) -> list[dict]:
    """Check all achievement conditions and grant new ones.
    Returns list of newly earned achievement dicts (for toast notifications).
    """
    # Get already earned
    existing = set()
    for r in conn.execute("SELECT achievement_id FROM achievements WHERE profile_id=?", (pid,)).fetchall():
        existing.add(r["achievement_id"])

    newly_earned = []
    now_str = date.today().isoformat()

    # Helper: grant if not already
    def grant(aid: str):
        if aid not in existing:
            conn.execute(
                "INSERT OR IGNORE INTO achievements (profile_id, achievement_id, achieved_at) VALUES (?,?,?)",
                (pid, aid, now_str),
            )
            existing.add(aid)
            if aid in ACHIEVEMENT_MAP:
                newly_earned.append(ACHIEVEMENT_MAP[aid])

    # --- Checks ---

    total_completed = get_total_completed(conn, pid)

    # First complete
    if total_completed >= 1:
        grant("first_complete")
    if total_completed >= 10:
        grant("total_10")
    if total_completed >= 50:
        grant("total_50")
    if total_completed >= 100:
        grant("total_100")
    if total_completed >= 500:
        grant("total_500")

    # Daily counts
    today_count = get_today_completed_count(conn, pid)
    if today_count >= 5:
        grant("daily_5")
    if today_count >= 10:
        grant("daily_10")

    # Streak
    streak = get_completion_streak(conn, pid)
    if streak >= 3:
        grant("streak_3")
    if streak >= 7:
        grant("streak_7")
    if streak >= 14:
        grant("streak_14")
    if streak >= 30:
        grant("streak_30")
    if streak >= 100:
        grant("streak_100")

    # Week 100%
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    if today.weekday() >= 4:  # Only check from Friday onwards
        week_row = conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) as done "
            "FROM todos WHERE profile_id=? AND due_date BETWEEN ? AND ?",
            (pid, monday.isoformat(), sunday.isoformat()),
        ).fetchone()
        if week_row and week_row["total"] > 0 and week_row["done"] == week_row["total"]:
            grant("week_100")

    # Focus 60 min
    focus_row = conn.execute(
        "SELECT SUM(hours) FROM work_logs WHERE profile_id=? AND title LIKE '집중 모드 %'",
        (pid,),
    ).fetchone()
    if focus_row and (focus_row[0] or 0) >= 1.0:
        grant("focus_60")

    # Month perfect (every day of current month has at least one completion)
    first_of_month = today.replace(day=1)
    if today.day >= 28:  # Only check near end of month
        all_days_done = True
        for day_num in range(1, today.day + 1):
            d = date(today.year, today.month, day_num)
            r = conn.execute(
                "SELECT 1 FROM todos WHERE profile_id=? AND completed=1 AND date(completed_at)=? LIMIT 1",
                (pid, d.isoformat()),
            ).fetchone()
            if not r:
                all_days_done = False
                break
        if all_days_done and today.day >= 28:
            grant("month_perfect")

    # Early bird (completed before 9am)
    early = conn.execute(
        "SELECT 1 FROM todos WHERE profile_id=? AND completed=1 AND time(completed_at) < '09:00:00' LIMIT 1",
        (pid,),
    ).fetchone()
    if early:
        grant("early_bird")

    # Night owl (completed after 11pm)
    night = conn.execute(
        "SELECT 1 FROM todos WHERE profile_id=? AND completed=1 AND time(completed_at) >= '23:00:00' LIMIT 1",
        (pid,),
    ).fetchone()
    if night:
        grant("night_owl")

    # Category master (completed in 3+ categories)
    cat_row = conn.execute(
        "SELECT COUNT(DISTINCT category_id) FROM todos WHERE profile_id=? AND completed=1 AND category_id IS NOT NULL",
        (pid,),
    ).fetchone()
    if cat_row and cat_row[0] >= 3:
        grant("category_master")

    return newly_earned
