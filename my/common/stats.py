"""Dashboard statistics helpers shared across planner apps."""

from datetime import date, timedelta


def get_week_range(ref_date: date | None = None) -> tuple[date, date]:
    today = ref_date or date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def get_stats(conn, pid: int) -> dict:
    today_str = date.today().isoformat()
    week_start, week_end = get_week_range()
    ws, we = week_start.isoformat(), week_end.isoformat()

    row = conn.execute("""
        SELECT
          SUM(CASE WHEN due_date <= :today AND completed = 0 THEN 1 ELSE 0 END),
          SUM(CASE WHEN completed = 1 AND date(completed_at) = :today THEN 1 ELSE 0 END),
          SUM(CASE WHEN completed = 0 AND due_date < :today AND due_date IS NOT NULL THEN 1 ELSE 0 END),
          SUM(CASE WHEN due_date BETWEEN :ws AND :we THEN 1 ELSE 0 END),
          SUM(CASE WHEN due_date BETWEEN :ws AND :we AND completed = 1 THEN 1 ELSE 0 END),
          COUNT(*)
        FROM todos WHERE profile_id = :pid
    """, {"today": today_str, "ws": ws, "we": we, "pid": pid}).fetchone()

    today_pending = row[0] or 0
    completed_today = row[1] or 0
    overdue = row[2] or 0
    week_total = row[3] or 0
    week_completed = row[4] or 0

    week_events = conn.execute(
        "SELECT COUNT(*) FROM events WHERE date(start_time) BETWEEN ? AND ? AND profile_id=?",
        (ws, we, pid),
    ).fetchone()[0]

    return {
        "completed_today": completed_today,
        "total_today": today_pending + completed_today,
        "overdue": overdue,
        "week_total": week_total,
        "week_completed": week_completed,
        "week_rate": round(week_completed / week_total * 100) if week_total > 0 else 0,
        "week_events": week_events,
    }


def get_weekly_chart_data(conn, pid: int) -> dict:
    today = date.today()
    range_start = today - timedelta(weeks=3, days=today.weekday())
    range_end = today - timedelta(days=today.weekday()) + timedelta(days=6)

    rows = conn.execute(
        "SELECT due_date, completed FROM todos WHERE profile_id=? AND due_date BETWEEN ? AND ?",
        (pid, range_start.isoformat(), range_end.isoformat()),
    ).fetchall()

    labels, completed_data, total_data = [], [], []
    for i in range(3, -1, -1):
        ws = today - timedelta(weeks=i, days=today.weekday())
        we = ws + timedelta(days=6)
        ws_s, we_s = ws.isoformat(), we.isoformat()
        labels.append(f"{ws.strftime('%m/%d')}~{we.strftime('%m/%d')}")
        total = sum(1 for r in rows if ws_s <= r["due_date"] <= we_s)
        done = sum(1 for r in rows if ws_s <= r["due_date"] <= we_s and r["completed"])
        total_data.append(total)
        completed_data.append(done)
    return {"labels": labels, "completed": completed_data, "total": total_data}


def week_number_in_month(d: date) -> int:
    first = d.replace(day=1)
    return (d.day + first.weekday()) // 7 + 1


# ── Smart Insights ──

WEEKDAY_KO = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
HOUR_LABELS = ["새벽(0-6)", "오전(6-12)", "오후(12-18)", "저녁(18-24)"]


def get_productivity_insights(conn, pid: int) -> dict:
    """Analyze productivity patterns from completed todos. Returns insights dict."""
    try:
        return _get_productivity_insights_inner(conn, pid)
    except Exception:
        return {}

def _get_productivity_insights_inner(conn, pid: int) -> dict:
    today = date.today()

    # 1. Weekday completion rate (last 8 weeks)
    range_start = (today - timedelta(weeks=8)).isoformat()
    rows = conn.execute(
        "SELECT date(completed_at) as d, strftime('%%w', completed_at) as dow "
        "FROM todos WHERE profile_id=? AND completed=1 AND completed_at IS NOT NULL AND completed_at >= ?",
        (pid, range_start),
    ).fetchall()

    dow_counts = [0] * 7
    for r in rows:
        if r["dow"] is None:
            continue
        dow = int(r["dow"])
        # SQLite %w: 0=Sunday, 1=Monday...
        py_dow = (dow - 1) % 7  # Convert to 0=Monday
        dow_counts[py_dow] += 1

    best_day_idx = max(range(7), key=lambda i: dow_counts[i]) if any(dow_counts) else 0
    best_day = WEEKDAY_KO[best_day_idx]
    best_day_count = dow_counts[best_day_idx]

    # 2. Time-of-day pattern
    hour_rows = conn.execute(
        "SELECT CAST(strftime('%%H', completed_at) AS INTEGER) as hr "
        "FROM todos WHERE profile_id=? AND completed=1 AND completed_at >= ? AND completed_at IS NOT NULL",
        (pid, range_start),
    ).fetchall()

    hour_buckets = [0, 0, 0, 0]  # dawn(0-6), morning(6-12), afternoon(12-18), evening(18-24)
    for r in hour_rows:
        hr = r["hr"]
        if hr is None:
            continue
        if hr < 6:
            hour_buckets[0] += 1
        elif hr < 12:
            hour_buckets[1] += 1
        elif hr < 18:
            hour_buckets[2] += 1
        else:
            hour_buckets[3] += 1

    best_period_idx = max(range(4), key=lambda i: hour_buckets[i]) if any(hour_buckets) else 1
    best_period = HOUR_LABELS[best_period_idx]

    # 3. Weekly comparison (this week vs last week)
    this_ws, this_we = get_week_range()
    last_ws = this_ws - timedelta(weeks=1)
    last_we = last_ws + timedelta(days=6)

    this_week = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=1 AND date(completed_at) BETWEEN ? AND ?",
        (pid, this_ws.isoformat(), this_we.isoformat()),
    ).fetchone()[0] or 0

    last_week = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=1 AND date(completed_at) BETWEEN ? AND ?",
        (pid, last_ws.isoformat(), last_we.isoformat()),
    ).fetchone()[0] or 0

    week_diff = this_week - last_week
    week_diff_pct = round((week_diff / last_week * 100)) if last_week > 0 else 0

    # 4. Category analysis (this month)
    month_start = today.replace(day=1).isoformat()
    cat_rows = conn.execute(
        "SELECT c.name, COUNT(*) as cnt "
        "FROM todos t LEFT JOIN categories c ON t.category_id = c.id "
        "WHERE t.profile_id=? AND t.completed=1 AND date(t.completed_at) >= ? AND c.name IS NOT NULL "
        "GROUP BY c.name ORDER BY cnt DESC LIMIT 5",
        (pid, month_start),
    ).fetchall()
    top_categories = [{"name": r["name"], "count": r["cnt"]} for r in cat_rows]

    # 5. Focus time total (this week)
    focus_hours = conn.execute(
        "SELECT COALESCE(SUM(hours), 0) FROM work_logs "
        "WHERE profile_id=? AND title LIKE '집중 모드 %%' AND log_date BETWEEN ? AND ?",
        (pid, this_ws.isoformat(), this_we.isoformat()),
    ).fetchone()[0] or 0

    return {
        "best_day": best_day,
        "best_day_count": best_day_count,
        "dow_counts": dow_counts,
        "best_period": best_period,
        "hour_buckets": hour_buckets,
        "this_week_completed": this_week,
        "last_week_completed": last_week,
        "week_diff": week_diff,
        "week_diff_pct": week_diff_pct,
        "top_categories": top_categories,
        "focus_hours": round(focus_hours, 1),
    }
