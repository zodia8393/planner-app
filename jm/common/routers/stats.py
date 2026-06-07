"""Stats router — /stats page."""

from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from common.stats import get_stats, get_weekly_chart_data, get_productivity_insights

router = APIRouter()


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        stats = get_stats(conn, pid)
        chart_data = get_weekly_chart_data(conn, pid)

        totals = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) FROM todos WHERE profile_id=?",
            (pid,),
        ).fetchone()
        total_all = totals[0] or 0
        total_completed = totals[1] or 0
        total_rate = round(total_completed / total_all * 100) if total_all > 0 else 0

        cat_stats = conn.execute("""
            SELECT c.name, c.color,
                   COUNT(t.id) as total,
                   SUM(CASE WHEN t.completed = 1 THEN 1 ELSE 0 END) as done
            FROM categories c
            LEFT JOIN todos t ON t.category_id = c.id AND t.profile_id = ?
            GROUP BY c.id, c.name, c.color
            ORDER BY c.sort_order
        """, (pid,)).fetchall()
        cat_stats = [{"name": r["name"], "color": r["color"], "total": r["total"], "done": r["done"] or 0} for r in cat_stats]

        today = date.today()
        month_labels = []
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            while m < 1:
                m += 12
                y -= 1
            month_labels.append(f"{y}-{m:02d}")
        first_month = month_labels[0] + "-01"

        created_rows = conn.execute(
            "SELECT strftime('%Y-%m', created_at) as m, COUNT(*) as c FROM todos WHERE profile_id=? AND created_at>=? GROUP BY m",
            (pid, first_month),
        ).fetchall()
        created_map = {r["m"]: r["c"] for r in created_rows}

        done_rows = conn.execute(
            "SELECT strftime('%Y-%m', completed_at) as m, COUNT(*) as c FROM todos WHERE profile_id=? AND completed=1 AND completed_at>=? GROUP BY m",
            (pid, first_month),
        ).fetchall()
        done_map = {r["m"]: r["c"] for r in done_rows}

        monthly_data = [{"label": lbl, "total": created_map.get(lbl, 0), "done": done_map.get(lbl, 0)} for lbl in month_labels]

        monthly_events = conn.execute("""
            SELECT strftime('%Y-%m', start_time) as m, COUNT(*) as c
            FROM events WHERE profile_id=?
            AND start_time >= date('now', 'start of year', 'localtime')
            GROUP BY m ORDER BY m
        """, (pid,)).fetchall()

        year_ago = (date.today() - timedelta(days=364)).isoformat()
        heatmap_data = conn.execute(
            "SELECT date(completed_at) as d, COUNT(*) as cnt FROM todos "
            "WHERE profile_id=? AND completed=1 AND completed_at>=? "
            "GROUP BY date(completed_at) ORDER BY d",
            (pid, year_ago)
        ).fetchall()
        heatmap = {row["d"]: row["cnt"] for row in heatmap_data if row["d"]}

        insights = get_productivity_insights(conn, pid)

    return S.render(request, "stats.html", {
        "page": "stats",
        "stats": stats,
        "chart_data": chart_data,
        "total_all": total_all,
        "total_completed": total_completed,
        "total_rate": total_rate,
        "cat_stats": cat_stats,
        "monthly_data": monthly_data,
        "monthly_events": [dict(r) for r in monthly_events],
        "heatmap": heatmap,
        "heatmap_start": year_ago,
        "heatmap_today": date.today().isoformat(),
        "insights": insights,
    })
