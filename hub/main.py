"""
Planner Hub - Master Dashboard
Aggregates metrics from JM, My, Work planners via read-only SQLite access.
"""

import json
import sqlite3
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Planner Hub")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

DATA_FILE = Path("/data/links.json") if Path("/data").exists() else BASE_DIR / "data" / "links.json"

# DB paths (relative to project root, one level up from hub/)
PROJECT_ROOT = BASE_DIR.parent
DB_PATHS = {
    "jm": PROJECT_ROOT / "jm" / "data" / "work.db",
    "my": PROJECT_ROOT / "my" / "data" / "planner.db",
    "work": PROJECT_ROOT / "work" / "data" / "work.db",
}

PLANNER_META = {
    "jm": {"name": "JM 플래너", "icon": "📋", "color": "indigo", "url": "https://jm-planner.fly.dev"},
    "my": {"name": "My 플래너", "icon": "💜", "color": "pink", "url": "https://my-planner.fly.dev"},
    "work": {"name": "Work 플래너", "icon": "👔", "color": "emerald", "url": ""},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_work_url() -> str:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text()).get("work_url", "")
    return ""


def save_work_url(url: str):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps({"work_url": url}))


def _connect(db_path: Path):
    """Open a read-only SQLite connection. Returns None if DB missing."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _safe_query(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only query, returning list of dicts. Empty on failure."""
    conn = _connect(db_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _safe_scalar(db_path: Path, sql: str, params: tuple = (), default=0):
    """Run a query returning a single scalar value."""
    conn = _connect(db_path)
    if conn is None:
        return default
    try:
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return default
        val = row[0]
        return val if val is not None else default
    except Exception:
        return default
    finally:
        conn.close()


def _db_online(key: str) -> bool:
    return DB_PATHS[key].exists()


def _check_url_health(url: str, timeout: float = 3.0) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/health", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _week_range(today: date) -> tuple[str, str]:
    """Return (monday, sunday) ISO strings for the week containing today."""
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


# ---------------------------------------------------------------------------
# Data aggregation
# ---------------------------------------------------------------------------

def gather_dashboard_data() -> dict:
    today_str = date.today().isoformat()
    now = datetime.now()
    week_start, week_end = _week_range(date.today())
    next_7 = (date.today() + timedelta(days=7)).isoformat()

    planners = {}
    total_pending = 0
    total_completed_today = 0
    all_events = []
    total_week_hours = 0.0

    for key, db_path in DB_PATHS.items():
        online = _db_online(key)
        meta = dict(PLANNER_META[key])
        if key == "work":
            meta["url"] = load_work_url()
            meta["url_healthy"] = _check_url_health(meta["url"])

        if not online:
            planners[key] = {
                **meta,
                "online": False,
                "pending": 0,
                "completed_today": 0,
                "events_7d": 0,
                "hours_today": 0.0,
            }
            continue

        # Pending todos (not completed)
        pending = _safe_scalar(db_path, "SELECT COUNT(*) FROM todos WHERE completed = 0")

        # Completed today
        completed_today = _safe_scalar(
            db_path,
            "SELECT COUNT(*) FROM todos WHERE completed = 1 AND date(completed_at) = ?",
            (today_str,),
        )

        # Upcoming events (next 7 days): start_time is like '2026-05-19T10:00'
        events_7d = _safe_scalar(
            db_path,
            "SELECT COUNT(*) FROM events WHERE date(start_time) >= ? AND date(start_time) <= ?",
            (today_str, next_7),
        )

        # Today's work hours
        hours_today = _safe_scalar(
            db_path,
            "SELECT COALESCE(SUM(hours), 0) FROM work_logs WHERE log_date = ?",
            (today_str,),
            default=0.0,
        )

        # Collect upcoming events for merged list
        event_rows = _safe_query(
            db_path,
            "SELECT title, start_time, all_day FROM events WHERE date(start_time) >= ? AND date(start_time) <= ? ORDER BY start_time",
            (today_str, next_7),
        )
        for ev in event_rows:
            all_events.append({**ev, "source": key, "source_name": meta["name"], "color": meta["color"]})

        # Week hours for this planner
        week_hours = _safe_scalar(
            db_path,
            "SELECT COALESCE(SUM(hours), 0) FROM work_logs WHERE log_date >= ? AND log_date <= ?",
            (week_start, week_end),
            default=0.0,
        )

        total_pending += pending
        total_completed_today += completed_today
        total_week_hours += week_hours

        planners[key] = {
            **meta,
            "online": True,
            "pending": pending,
            "completed_today": completed_today,
            "events_7d": events_7d,
            "hours_today": hours_today,
            "week_hours": week_hours,
        }

    # Sort merged events by start_time
    all_events.sort(key=lambda e: e.get("start_time", ""))

    # Completion rate
    total_tasks = total_pending + total_completed_today
    completion_rate = round(total_completed_today / total_tasks * 100, 1) if total_tasks > 0 else 0

    return {
        "today_str": today_str,
        "day_of_week": ["월", "화", "수", "목", "금", "토", "일"][date.today().weekday()],
        "now_str": now.strftime("%H:%M"),
        "total_pending": total_pending,
        "total_completed_today": total_completed_today,
        "completion_rate": completion_rate,
        "planners": planners,
        "all_events": all_events[:20],  # cap at 20
        "total_week_hours": round(total_week_hours, 1),
        "week_start": week_start,
        "week_end": week_end,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    data = gather_dashboard_data()
    return TEMPLATES.TemplateResponse(request, "dashboard.html", data)


@app.post("/update-work-url")
async def update_work_url(request: Request):
    body = await request.json()
    url = body.get("url", "")
    if url:
        save_work_url(url)
        return {"ok": True, "url": url}
    return {"ok": False}


@app.get("/health")
async def health():
    statuses = {k: v.exists() for k, v in DB_PATHS.items()}
    return {"status": "ok", "databases": statuses}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
