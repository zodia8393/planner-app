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

    total_today_pending = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE due_date<=? AND completed=0 AND profile_id=?",
        (today_str, pid),
    ).fetchone()[0]
    completed_today = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE completed=1 AND date(completed_at)=? AND profile_id=?",
        (today_str, pid),
    ).fetchone()[0]
    total_today = total_today_pending + completed_today

    overdue = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE completed=0 AND due_date<? AND due_date IS NOT NULL AND profile_id=?",
        (today_str, pid),
    ).fetchone()[0]

    week_total = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE due_date BETWEEN ? AND ? AND profile_id=?",
        (week_start.isoformat(), week_end.isoformat(), pid),
    ).fetchone()[0]
    week_completed = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE due_date BETWEEN ? AND ? AND completed=1 AND profile_id=?",
        (week_start.isoformat(), week_end.isoformat(), pid),
    ).fetchone()[0]

    week_events = conn.execute(
        "SELECT COUNT(*) FROM events WHERE date(start_time) BETWEEN ? AND ? AND profile_id=?",
        (week_start.isoformat(), week_end.isoformat(), pid),
    ).fetchone()[0]

    return {
        "completed_today": completed_today,
        "total_today": total_today,
        "overdue": overdue,
        "week_total": week_total,
        "week_completed": week_completed,
        "week_rate": round(week_completed / week_total * 100) if week_total > 0 else 0,
        "week_events": week_events,
    }


def get_weekly_chart_data(conn, pid: int) -> dict:
    labels = []
    completed_data = []
    total_data = []
    today = date.today()
    for i in range(3, -1, -1):
        week_start = today - timedelta(weeks=i, days=today.weekday())
        week_end = week_start + timedelta(days=6)
        label = f"{week_start.strftime('%m/%d')}~{week_end.strftime('%m/%d')}"
        labels.append(label)
        total = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE due_date BETWEEN ? AND ? AND profile_id=?",
            (week_start.isoformat(), week_end.isoformat(), pid),
        ).fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE due_date BETWEEN ? AND ? AND completed=1 AND profile_id=?",
            (week_start.isoformat(), week_end.isoformat(), pid),
        ).fetchone()[0]
        total_data.append(total)
        completed_data.append(done)
    return {"labels": labels, "completed": completed_data, "total": total_data}


def week_number_in_month(d: date) -> int:
    first = d.replace(day=1)
    return (d.day + first.weekday()) // 7 + 1
