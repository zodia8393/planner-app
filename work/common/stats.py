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
