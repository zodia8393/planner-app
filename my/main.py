"""
My Planner - Universal personal planner with profile isolation & shared folders
FastAPI + Jinja2 + HTMX + Tailwind CSS + SQLite
"""

import os
import sys
from pathlib import Path as _P
_app_dir = _P(__file__).resolve().parent
sys.path.insert(0, str(_app_dir.parent))
sys.path.insert(0, str(_app_dir))
_env_path = _P(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import json
import uuid
import sqlite3
import calendar as cal_mod
import asyncio
import secrets
import hashlib
import shutil
import zipfile
import io
from datetime import datetime, date as date_mod, timedelta
from functools import partial
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (
    FastAPI, Request, Form, Query, HTTPException, Response,
    UploadFile, File,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

import uvicorn

# ── Common modules ──
from common.utils import fix_mojibake, clamp_priority, validate_date_str, validate_datetime_str, clamp_text
from common.filters import register_filters, render_error_page
from common.middleware import EventBus, CSRFMiddleware, SyncBroadcastMiddleware, patch_formparser_utf8
from common.constants import PRIORITY_MAP, REPEAT_MAP, WEEKDAY_NAMES
from common.recurrence import next_occurrence, expand_recurring_events
from common.stats import get_stats, get_weekly_chart_data, week_number_in_month, get_week_range
from common.db import get_db as _common_get_db
from common.image import MAGIC_BYTES, _check_image_magic
from common.holidays import KOREAN_HOLIDAYS, get_holidays_for_month
from common.excel import parse_excel_with_merges, infer_field_type
from common.gcal import (
    GCAL_CLIENT_ID, GCAL_CLIENT_SECRET, GCAL_SCOPES,
    GCAL_AUTH_URL, GCAL_TOKEN_URL, GCAL_API_BASE,
    gcal_redirect_uri, gcal_refresh_token,
    gcal_fetch_events, gcal_push_event, gcal_update_event, gcal_delete_event,
)


# ── Starlette FormParser latin-1 -> utf-8 patch ──
patch_formparser_utf8()


# ── SSE EventBus ──
event_bus = EventBus()


# ── Path setup ──
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "planner.db"
SHARED_DIR = BASE_DIR / "data" / "shared"
(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
SHARED_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# ── FastAPI app ──
@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

app = FastAPI(title="My Planner", docs_url=None, redoc_url=None, lifespan=lifespan)


OPEN_PATHS = {"/setup", "/health", "/sse", "/static", "/cal", "/settings/gcal/callback", "/auth/google/login", "/auth/google/callback", "/privacy", "/.well-known"}


class ProfileCheckMiddleware(BaseHTTPMiddleware):
    """Redirect to /setup if no valid profile cookie for protected routes."""
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Allow open paths
        if path in OPEN_PATHS or path.startswith("/static") or path.startswith("/setup") or path.startswith("/worklog-images") or path.startswith("/backgrounds") or path.startswith("/.well-known") or path == "/api/qr-code" or path == "/sync-profile":
            return await call_next(request)
        # Check cookie
        cookie_val = request.cookies.get("planner_profile")
        if not cookie_val:
            return RedirectResponse("/setup", status_code=303)
        return await call_next(request)


app.add_middleware(ProfileCheckMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SyncBroadcastMiddleware, event_bus=event_bus,
                   skip_paths=("/worklogs/upload-image",),
                   skip_prefixes=("/files/",))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
BG_DIR = BASE_DIR / "data" / "backgrounds"
BG_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/backgrounds", StaticFiles(directory=str(BG_DIR)), name="backgrounds")
WORKLOG_IMG_DIR = BASE_DIR / "data" / "worklog_images"
WORKLOG_IMG_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/worklog-images", StaticFiles(directory=str(WORKLOG_IMG_DIR)), name="worklog_images")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ── Client IP / Network Group helpers ──
def get_client_ip(request: Request) -> str:
    """Get the real client IP, checking X-Forwarded-For first."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def _ip_to_network_group(ip: str) -> str:
    """Extract network group from an IP string."""
    parts = ip.split(".")
    if len(parts) >= 3:
        return ".".join(parts[:3])
    if ":" in ip:
        segments = ip.split(":")
        return ":".join(segments[:3]) if len(segments) >= 3 else ip
    return ip


def get_network_group(request: Request) -> str:
    """First 3 octets of client IP as network group identifier."""
    return _ip_to_network_group(get_client_ip(request))


# ── Profile helpers ──
def get_profile_id(request: Request) -> Optional[int]:
    """Read profile_id from cookie token. Returns None if not set."""
    token = request.cookies.get("planner_profile")
    if token and len(token) > 8:
        with get_db() as conn:
            row = conn.execute("SELECT id FROM profiles WHERE token=?", (token,)).fetchone()
            if row:
                return row["id"]
    return None


def require_profile(request: Request) -> int:
    """Get profile_id or raise HTTPException to redirect to setup."""
    pid = get_profile_id(request)
    if pid is None:
        raise HTTPException(status_code=303, headers={"Location": "/setup"})
    # Verify profile exists
    with get_db() as conn:
        row = conn.execute("SELECT id FROM profiles WHERE id=?", (pid,)).fetchone()
        if not row:
            raise HTTPException(status_code=303, headers={"Location": "/setup"})
    return pid


def get_profile_name(request: Request) -> str:
    pid = get_profile_id(request)
    if pid:
        with get_db() as conn:
            row = conn.execute("SELECT name FROM profiles WHERE id=?", (pid,)).fetchone()
            if row:
                return row["name"]
    return ""


def get_bg_setting(profile_id: int) -> dict:
    """Get background setting for a profile."""
    default = {"type": "none", "preset": "", "image": "", "opacity": 0.7}
    if not profile_id:
        return default
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT value FROM user_settings WHERE profile_id=? AND key='background'",
                (profile_id,),
            ).fetchone()
            if row and row["value"]:
                return json.loads(row["value"])
    except Exception:
        pass
    return default


def render(request: Request, name: str, context: dict = None):
    """TemplateResponse wrapper that injects the active profile."""
    ctx = context or {}
    pid = get_profile_id(request)
    if pid:
        try:
            with get_db() as conn:
                row = conn.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
                if row:
                    ctx["active_profile"] = dict(row)
                    ctx["active_profile_id"] = pid
                else:
                    ctx["active_profile"] = None
                    ctx["active_profile_id"] = None
        except Exception:
            ctx["active_profile"] = None
            ctx["active_profile_id"] = None
    else:
        ctx["active_profile"] = None
        ctx["active_profile_id"] = None
    ctx.setdefault("today", date_mod.today())
    ctx.setdefault("bg_setting", get_bg_setting(pid))
    return templates.TemplateResponse(request, name, ctx)


# ── SSE endpoint ──

@app.get("/sse")
async def sse_stream(request: Request):
    sid, queue = event_bus.subscribe()

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    page = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"event: sync\ndata: {page}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            event_bus.unsubscribe(sid)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return HTMLResponse(render_error_page(404, "페이지를 찾을 수 없습니다"), status_code=404)


@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc):
    return HTMLResponse(render_error_page(405, "허용되지 않는 요청입니다"), status_code=405)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return HTMLResponse(render_error_page(500, "서버 오류가 발생했습니다"), status_code=500)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    messages = {
        400: "잘못된 요청입니다",
        403: "접근 권한이 없습니다",
        404: "페이지를 찾을 수 없습니다",
        405: "허용되지 않는 요청입니다",
        422: "입력값이 올바르지 않습니다",
    }
    msg = exc.detail if isinstance(exc.detail, str) and exc.detail != "Not Found" else messages.get(exc.status_code, "오류가 발생했습니다")
    return HTMLResponse(render_error_page(exc.status_code, msg), status_code=exc.status_code)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return HTMLResponse(render_error_page(500, "서버 오류가 발생했습니다"), status_code=500)

register_filters(templates)


# ── DB management ──
get_db = partial(_common_get_db, DB_PATH)


def init_db():
    """Initialize DB schema."""
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            token TEXT NOT NULL DEFAULT '',
            last_ip TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT '#6366f1',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            priority INTEGER DEFAULT 2,
            category_id INTEGER,
            due_date TEXT,
            completed INTEGER DEFAULT 0,
            completed_at TEXT,
            sort_order INTEGER DEFAULT 0,
            repeat_type TEXT DEFAULT 'none',
            tags TEXT DEFAULT '[]',
            assignee TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            todo_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (todo_id) REFERENCES todos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            start_time TEXT NOT NULL,
            end_time TEXT,
            all_day INTEGER DEFAULT 0,
            category_id INTEGER,
            color TEXT DEFAULT '#6366f1',
            memo TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS memos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            author TEXT NOT NULL DEFAULT '',
            title TEXT DEFAULT '',
            content TEXT NOT NULL,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS ddays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            target_date TEXT NOT NULL,
            icon TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS shared_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            uploader_profile_id INTEGER NOT NULL,
            network_group TEXT NOT NULL,
            uploaded_at TEXT DEFAULT (datetime('now', 'localtime')),
            file_size INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_date);
        CREATE INDEX IF NOT EXISTS idx_todos_completed ON todos(completed);
        CREATE INDEX IF NOT EXISTS idx_todos_profile ON todos(profile_id);
        CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);
        CREATE INDEX IF NOT EXISTS idx_events_profile ON events(profile_id);
        CREATE INDEX IF NOT EXISTS idx_memos_profile ON memos(profile_id);
        CREATE INDEX IF NOT EXISTS idx_shared_files_group ON shared_files(network_group);
        CREATE INDEX IF NOT EXISTS idx_categories_profile ON categories(profile_id);

        CREATE TABLE IF NOT EXISTS work_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            log_date TEXT NOT NULL DEFAULT (date('now', 'localtime')),
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            hours REAL DEFAULT 0,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_worklogs_profile ON work_logs(profile_id);
        CREATE INDEX IF NOT EXISTS idx_worklogs_date ON work_logs(log_date);

        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            network_group TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            priority INTEGER DEFAULT 0,
            pinned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_notices_group ON notices(network_group);

        CREATE TABLE IF NOT EXISTS form_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            fields TEXT NOT NULL DEFAULT '[]',
            emoji TEXT DEFAULT '📝',
            color TEXT DEFAULT '#6366f1',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS form_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            entry_date TEXT NOT NULL DEFAULT (date('now', 'localtime')),
            values_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (template_id) REFERENCES form_templates(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_form_entries_template ON form_entries(template_id);
        CREATE INDEX IF NOT EXISTS idx_form_entries_date ON form_entries(entry_date);

        CREATE TABLE IF NOT EXISTS gcal_tokens (
            profile_id INTEGER PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            token_expiry TEXT NOT NULL,
            calendar_id TEXT DEFAULT 'primary',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            profile_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY(profile_id, key)
        );

        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT DEFAULT '',
            description TEXT DEFAULT '',
            favicon TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS time_budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
            weekly_hours REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS todo_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL,
            items_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS automation_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL,
            trigger_type TEXT NOT NULL DEFAULT 'weekly',
            trigger_config TEXT NOT NULL DEFAULT '{}',
            action_type TEXT NOT NULL DEFAULT 'create_todo',
            action_config TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER DEFAULT 1,
            last_run TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            changes_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            profile_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);

        CREATE TABLE IF NOT EXISTS meal_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL,
            address TEXT DEFAULT '',
            category TEXT DEFAULT '',
            lat REAL,
            lng REAL,
            naver_id TEXT DEFAULT '',
            visited_count INTEGER DEFAULT 0,
            last_visited TEXT,
            excluded INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_meal_profile ON meal_places(profile_id);

        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            icon TEXT DEFAULT '✅',
            color TEXT DEFAULT '#6366f1',
            frequency TEXT DEFAULT 'daily',
            sort_order INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_habits_profile ON habits(profile_id);

        CREATE TABLE IF NOT EXISTS habit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            completed INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE,
            UNIQUE(habit_id, log_date)
        );
        CREATE INDEX IF NOT EXISTS idx_habit_logs_date ON habit_logs(log_date);
        CREATE INDEX IF NOT EXISTS idx_habit_logs_habit ON habit_logs(habit_id);

        CREATE TABLE IF NOT EXISTS onboarding_progress (
            profile_id INTEGER PRIMARY KEY,
            step1_done INTEGER DEFAULT 0,
            step2_done INTEGER DEFAULT 0,
            step3_done INTEGER DEFAULT 0,
            step4_done INTEGER DEFAULT 0,
            dismissed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS morning_brief_settings (
            profile_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            hour INTEGER DEFAULT 8,
            minute INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS app_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            visit_date TEXT NOT NULL,
            UNIQUE(profile_id, visit_date)
        );
        CREATE INDEX IF NOT EXISTS idx_visits_profile ON app_visits(profile_id);
        """)

        # Migration: add token column if missing (existing DBs)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()]
        if "token" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN token TEXT NOT NULL DEFAULT ''")
            for row in conn.execute("SELECT id FROM profiles WHERE token=''").fetchall():
                conn.execute("UPDATE profiles SET token=? WHERE id=?", (uuid.uuid4().hex + uuid.uuid4().hex, row[0]))

        # Migration: add gcal_event_id to events
        ev_cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
        if "gcal_event_id" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN gcal_event_id TEXT DEFAULT ''")

        # Migration: add emoji/color to form_templates
        ft_cols = [r[1] for r in conn.execute("PRAGMA table_info(form_templates)").fetchall()]
        if "emoji" not in ft_cols:
            conn.execute("ALTER TABLE form_templates ADD COLUMN emoji TEXT DEFAULT '📝'")
        if "color" not in ft_cols:
            conn.execute("ALTER TABLE form_templates ADD COLUMN color TEXT DEFAULT '#6366f1'")
        if "frequency" not in ft_cols:
            conn.execute("ALTER TABLE form_templates ADD COLUMN frequency TEXT DEFAULT 'daily'")

        # Migration: add recurrence columns to todos and events
        todo_cols = [r[1] for r in conn.execute("PRAGMA table_info(todos)").fetchall()]
        if "recurrence_end" not in todo_cols:
            conn.execute("ALTER TABLE todos ADD COLUMN recurrence_end TEXT DEFAULT ''")
        if "recurrence" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN recurrence TEXT DEFAULT ''")
        if "recurrence_end" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN recurrence_end TEXT DEFAULT ''")

        # Migration: add energy_level column to todos (1=Low, 2=Medium, 3=High)
        if "energy_level" not in todo_cols:
            conn.execute("ALTER TABLE todos ADD COLUMN energy_level INTEGER DEFAULT 2")

        # Migration: add gcal sync columns to events
        if "gcal_sync_status" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN gcal_sync_status TEXT DEFAULT ''")
        if "gcal_last_synced" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN gcal_last_synced TEXT DEFAULT ''")

        # Migration: add Google OAuth columns to profiles
        prof_cols = [r[1] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()]
        if "google_sub" not in prof_cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN google_sub TEXT DEFAULT ''")
        if "google_email" not in prof_cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN google_email TEXT DEFAULT ''")

        # Migration: reminder_offsets for events, todos, ddays
        ev_cols2 = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
        if "reminder_offsets" not in ev_cols2:
            conn.execute("ALTER TABLE events ADD COLUMN reminder_offsets TEXT DEFAULT NULL")
        todo_cols2 = [r[1] for r in conn.execute("PRAGMA table_info(todos)").fetchall()]
        if "reminder_offsets" not in todo_cols2:
            conn.execute("ALTER TABLE todos ADD COLUMN reminder_offsets TEXT DEFAULT NULL")
        dday_cols = [r[1] for r in conn.execute("PRAGMA table_info(ddays)").fetchall()]
        if "reminder_offsets" not in dday_cols:
            conn.execute("ALTER TABLE ddays ADD COLUMN reminder_offsets TEXT DEFAULT NULL")

        # Migration: habits time-based tracking columns
        habit_cols = [r[1] for r in conn.execute("PRAGMA table_info(habits)").fetchall()]
        if "target_count" not in habit_cols:
            conn.execute("ALTER TABLE habits ADD COLUMN target_count INTEGER DEFAULT 1")
        if "frequency_detail" not in habit_cols:
            conn.execute("ALTER TABLE habits ADD COLUMN frequency_detail TEXT DEFAULT NULL")
        if "reminder_times" not in habit_cols:
            conn.execute("ALTER TABLE habits ADD COLUMN reminder_times TEXT DEFAULT NULL")

        # Migration: habit_logs time/count columns + relax UNIQUE constraint
        hl_cols = [r[1] for r in conn.execute("PRAGMA table_info(habit_logs)").fetchall()]
        if "log_time" not in hl_cols:
            conn.execute("ALTER TABLE habit_logs ADD COLUMN log_time TEXT DEFAULT NULL")
        if "count" not in hl_cols:
            conn.execute("ALTER TABLE habit_logs ADD COLUMN count INTEGER DEFAULT 1")
        # Recreate habit_logs without UNIQUE(habit_id, log_date) for counter/time habits
        try:
            indexes = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='habit_logs'").fetchall()
            has_old_unique = any('habit_id' in (r[0] or '') and 'log_date' in (r[0] or '') and 'UNIQUE' in (r[0] or '').upper() for r in indexes)
            tbl_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='habit_logs'").fetchone()
            if tbl_sql and 'UNIQUE(habit_id, log_date)' in (tbl_sql[0] or ''):
                has_old_unique = True
            if has_old_unique:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS habit_logs_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        habit_id INTEGER NOT NULL,
                        profile_id INTEGER NOT NULL,
                        log_date TEXT NOT NULL,
                        log_time TEXT DEFAULT NULL,
                        count INTEGER DEFAULT 1,
                        completed INTEGER DEFAULT 1,
                        created_at TEXT DEFAULT (datetime('now', 'localtime')),
                        FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE
                    );
                    INSERT OR IGNORE INTO habit_logs_new (id, habit_id, profile_id, log_date, log_time, count, completed, created_at)
                        SELECT id, habit_id, profile_id, log_date, log_time, count, completed, created_at FROM habit_logs;
                    DROP TABLE habit_logs;
                    ALTER TABLE habit_logs_new RENAME TO habit_logs;
                    CREATE INDEX IF NOT EXISTS idx_habit_logs_date ON habit_logs(log_date);
                    CREATE INDEX IF NOT EXISTS idx_habit_logs_habit ON habit_logs(habit_id);
                """)
        except Exception:
            pass

        # notification_settings table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                target_type TEXT NOT NULL,
                offsets TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER DEFAULT 1,
                UNIQUE(profile_id, target_type)
            )
        """)

    # One-time cleanup: remove duplicate focus mode worklog entries
    with get_db() as conn:
        conn.execute("""
            DELETE FROM work_logs WHERE id NOT IN (
                SELECT MIN(id) FROM work_logs WHERE title LIKE '집중 모드 %' GROUP BY profile_id, log_date, title, hours
            ) AND title LIKE '집중 모드 %'
        """)

    # Initialize FTS5 full-text search indexes
    from common.search import init_fts
    with get_db() as fts_conn:
        init_fts(fts_conn)

    _seed_form_presets()


def _seed_form_presets():
    """Seed Korean admin form presets if not already present."""
    presets = [
        (
            "품의서", "기안/승인 요청 양식", "📋", "#6366f1",
            [
                {"name": "title", "label": "제목", "type": "text", "required": True},
                {"name": "draft_date", "label": "기안일", "type": "date", "required": True},
                {"name": "drafter", "label": "기안자", "type": "text", "required": True},
                {"name": "department", "label": "부서", "type": "text", "required": False},
                {"name": "amount", "label": "금액", "type": "number", "required": False},
                {"name": "purpose", "label": "목적", "type": "textarea", "required": True},
                {"name": "details", "label": "상세내역", "type": "textarea", "required": False},
                {"name": "attachment_memo", "label": "첨부파일 메모", "type": "text", "required": False},
                {"name": "approval_status", "label": "결재상태", "type": "select", "required": True, "options": ["대기", "승인", "반려"]},
            ],
        ),
        (
            "회의록", "회의 기록 양식", "🗓️", "#8b5cf6",
            [
                {"name": "meeting_name", "label": "회의명", "type": "text", "required": True},
                {"name": "meeting_datetime", "label": "일시", "type": "datetime", "required": True},
                {"name": "location", "label": "장소", "type": "text", "required": False},
                {"name": "attendees", "label": "참석자", "type": "textarea", "required": True},
                {"name": "agenda", "label": "안건", "type": "textarea", "required": True},
                {"name": "discussion", "label": "논의내용", "type": "textarea", "required": False},
                {"name": "decisions", "label": "결정사항", "type": "textarea", "required": False},
                {"name": "follow_up", "label": "후속조치", "type": "textarea", "required": False},
            ],
        ),
        (
            "업무일지", "일일 업무 보고 양식", "📝", "#10b981",
            [
                {"name": "report_date", "label": "날짜", "type": "date", "required": True},
                {"name": "author", "label": "작성자", "type": "text", "required": True},
                {"name": "today_work", "label": "오늘 업무", "type": "textarea", "required": True},
                {"name": "tomorrow_plan", "label": "내일 계획", "type": "textarea", "required": False},
                {"name": "issues", "label": "이슈/건의", "type": "textarea", "required": False},
                {"name": "work_hours", "label": "근무시간", "type": "number", "required": False},
            ],
        ),
        (
            "출장보고서", "출장 결과 보고 양식", "✈️", "#0ea5e9",
            [
                {"name": "title", "label": "출장 제목", "type": "text", "required": True},
                {"name": "traveler", "label": "출장자", "type": "text", "required": True},
                {"name": "department", "label": "부서", "type": "text", "required": False},
                {"name": "start_date", "label": "출장 시작일", "type": "date", "required": True},
                {"name": "end_date", "label": "출장 종료일", "type": "date", "required": True},
                {"name": "destination", "label": "출장지", "type": "text", "required": True},
                {"name": "purpose", "label": "출장 목적", "type": "textarea", "required": True},
                {"name": "result", "label": "출장 성과", "type": "textarea", "required": True},
                {"name": "expenses", "label": "지출 내역", "type": "textarea", "required": False},
                {"name": "total_cost", "label": "총 비용(원)", "type": "number", "required": False},
                {"name": "follow_up", "label": "후속 조치", "type": "textarea", "required": False},
            ],
        ),
        (
            "지출결의서", "경비 지출 승인 양식", "💰", "#f59e0b",
            [
                {"name": "title", "label": "지출 건명", "type": "text", "required": True},
                {"name": "request_date", "label": "신청일", "type": "date", "required": True},
                {"name": "requester", "label": "신청자", "type": "text", "required": True},
                {"name": "department", "label": "부서", "type": "text", "required": False},
                {"name": "category", "label": "지출 구분", "type": "select", "required": True, "options": ["업무추진비", "여비교통비", "소모품비", "교육훈련비", "통신비", "기타"]},
                {"name": "amount", "label": "금액(원)", "type": "number", "required": True},
                {"name": "payment_method", "label": "결제수단", "type": "select", "required": False, "options": ["법인카드", "개인카드(추후정산)", "현금", "계좌이체"]},
                {"name": "details", "label": "지출 상세", "type": "textarea", "required": True},
                {"name": "receipt_note", "label": "영수증 비고", "type": "text", "required": False},
                {"name": "approval_status", "label": "결재상태", "type": "select", "required": True, "options": ["대기", "승인", "반려"]},
            ],
        ),
        (
            "휴가신청서", "연차/반차/특별휴가 신청", "🏖️", "#14b8a6",
            [
                {"name": "applicant", "label": "신청자", "type": "text", "required": True},
                {"name": "department", "label": "부서", "type": "text", "required": False},
                {"name": "leave_type", "label": "휴가 종류", "type": "select", "required": True, "options": ["연차", "오전반차", "오후반차", "병가", "경조휴가", "공가", "특별휴가"]},
                {"name": "start_date", "label": "시작일", "type": "date", "required": True},
                {"name": "end_date", "label": "종료일", "type": "date", "required": True},
                {"name": "days", "label": "사용일수", "type": "number", "required": True},
                {"name": "reason", "label": "사유", "type": "textarea", "required": True},
                {"name": "emergency_contact", "label": "비상연락처", "type": "text", "required": False},
                {"name": "handover", "label": "업무 인수인계", "type": "textarea", "required": False},
                {"name": "approval_status", "label": "승인상태", "type": "select", "required": True, "options": ["신청", "승인", "반려"]},
            ],
        ),
        (
            "주간업무보고", "주간 업무 현황 보고", "📊", "#6366f1",
            [
                {"name": "week_range", "label": "보고 기간", "type": "text", "required": True},
                {"name": "author", "label": "작성자", "type": "text", "required": True},
                {"name": "department", "label": "부서", "type": "text", "required": False},
                {"name": "completed", "label": "금주 완료 업무", "type": "textarea", "required": True},
                {"name": "in_progress", "label": "진행 중 업무", "type": "textarea", "required": False},
                {"name": "next_week", "label": "차주 계획", "type": "textarea", "required": True},
                {"name": "issues", "label": "이슈/리스크", "type": "textarea", "required": False},
                {"name": "kpi_note", "label": "성과 지표 메모", "type": "textarea", "required": False},
            ],
        ),
        (
            "프로젝트 기획서", "프로젝트 계획 및 제안 양식", "🚀", "#8b5cf6",
            [
                {"name": "project_name", "label": "프로젝트명", "type": "text", "required": True},
                {"name": "pm", "label": "담당자(PM)", "type": "text", "required": True},
                {"name": "start_date", "label": "시작일", "type": "date", "required": True},
                {"name": "end_date", "label": "종료일", "type": "date", "required": True},
                {"name": "background", "label": "추진 배경", "type": "textarea", "required": True},
                {"name": "objective", "label": "목표", "type": "textarea", "required": True},
                {"name": "scope", "label": "범위", "type": "textarea", "required": True},
                {"name": "budget", "label": "예산(원)", "type": "number", "required": False},
                {"name": "milestones", "label": "주요 마일스톤", "type": "textarea", "required": False},
                {"name": "risks", "label": "리스크/대응방안", "type": "textarea", "required": False},
                {"name": "expected_outcome", "label": "기대 효과", "type": "textarea", "required": False},
            ],
        ),
        (
            "인수인계서", "업무 인수인계 양식", "🤝", "#f97316",
            [
                {"name": "handover_date", "label": "인수인계일", "type": "date", "required": True},
                {"name": "from_person", "label": "인계자", "type": "text", "required": True},
                {"name": "to_person", "label": "인수자", "type": "text", "required": True},
                {"name": "department", "label": "부서", "type": "text", "required": False},
                {"name": "responsibilities", "label": "담당 업무 목록", "type": "textarea", "required": True},
                {"name": "ongoing", "label": "진행 중 업무", "type": "textarea", "required": True},
                {"name": "pending", "label": "미결/보류 사항", "type": "textarea", "required": False},
                {"name": "contacts", "label": "주요 연락처", "type": "textarea", "required": False},
                {"name": "files_location", "label": "관련 자료 위치", "type": "textarea", "required": False},
                {"name": "notes", "label": "특이사항/주의점", "type": "textarea", "required": False},
            ],
        ),
        (
            "교육훈련보고서", "교육/세미나 참가 보고", "🎓", "#a855f7",
            [
                {"name": "title", "label": "교육명", "type": "text", "required": True},
                {"name": "trainee", "label": "참가자", "type": "text", "required": True},
                {"name": "start_date", "label": "시작일", "type": "date", "required": True},
                {"name": "end_date", "label": "종료일", "type": "date", "required": True},
                {"name": "institution", "label": "교육기관/장소", "type": "text", "required": False},
                {"name": "hours", "label": "교육시간", "type": "number", "required": False},
                {"name": "content_summary", "label": "교육 내용 요약", "type": "textarea", "required": True},
                {"name": "key_takeaways", "label": "핵심 시사점", "type": "textarea", "required": True},
                {"name": "application_plan", "label": "업무 적용 계획", "type": "textarea", "required": False},
                {"name": "cost", "label": "교육비(원)", "type": "number", "required": False},
            ],
        ),
        (
            "검수보고서", "납품물/결과물 검수 양식", "🔍", "#ef4444",
            [
                {"name": "title", "label": "검수 건명", "type": "text", "required": True},
                {"name": "inspector", "label": "검수자", "type": "text", "required": True},
                {"name": "inspect_date", "label": "검수일", "type": "date", "required": True},
                {"name": "contractor", "label": "납품업체/담당자", "type": "text", "required": False},
                {"name": "deliverables", "label": "납품 내역", "type": "textarea", "required": True},
                {"name": "criteria", "label": "검수 기준", "type": "textarea", "required": True},
                {"name": "result", "label": "검수 결과", "type": "select", "required": True, "options": ["합격", "조건부합격", "불합격", "재검수"]},
                {"name": "defects", "label": "하자/보완사항", "type": "textarea", "required": False},
                {"name": "opinion", "label": "검수 의견", "type": "textarea", "required": False},
            ],
        ),
        (
            "견적요청서", "견적 요청/비교 양식", "💼", "#64748b",
            [
                {"name": "title", "label": "요청 건명", "type": "text", "required": True},
                {"name": "requester", "label": "요청자", "type": "text", "required": True},
                {"name": "request_date", "label": "요청일", "type": "date", "required": True},
                {"name": "deadline", "label": "회신 기한", "type": "date", "required": False},
                {"name": "vendor", "label": "견적 업체", "type": "text", "required": False},
                {"name": "items", "label": "요청 품목/서비스", "type": "textarea", "required": True},
                {"name": "quantity", "label": "수량/규모", "type": "text", "required": False},
                {"name": "budget_range", "label": "예산 범위", "type": "text", "required": False},
                {"name": "conditions", "label": "요구 조건", "type": "textarea", "required": False},
                {"name": "notes", "label": "비고", "type": "textarea", "required": False},
            ],
        ),
        (
            "시말서", "사고/위반 경위 보고", "⚠️", "#dc2626",
            [
                {"name": "author", "label": "작성자", "type": "text", "required": True},
                {"name": "department", "label": "부서", "type": "text", "required": False},
                {"name": "incident_date", "label": "발생일시", "type": "datetime", "required": True},
                {"name": "incident_type", "label": "사건 유형", "type": "select", "required": True, "options": ["안전사고", "업무과실", "규정위반", "장비손상", "기타"]},
                {"name": "description", "label": "사건 경위", "type": "textarea", "required": True},
                {"name": "cause", "label": "원인 분석", "type": "textarea", "required": True},
                {"name": "damage", "label": "피해/손실 내역", "type": "textarea", "required": False},
                {"name": "corrective_action", "label": "시정 조치", "type": "textarea", "required": True},
                {"name": "prevention", "label": "재발 방지 대책", "type": "textarea", "required": True},
            ],
        ),
    ]
    with get_db() as conn:
        for name, desc, emoji, color, fields in presets:
            existing = conn.execute(
                "SELECT id FROM form_templates WHERE name=? AND profile_id=0", (name,)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO form_templates (profile_id, name, description, fields, emoji, color) VALUES (0, ?, ?, ?, ?, ?)",
                    (name, desc, json.dumps(fields, ensure_ascii=False), emoji, color),
                )


def ensure_default_categories(conn, profile_id: int):
    """Create default categories for a new profile."""
    existing = conn.execute(
        "SELECT COUNT(*) FROM categories WHERE profile_id=?", (profile_id,)
    ).fetchone()[0]
    if existing == 0:
        conn.executemany(
            "INSERT INTO categories (profile_id, name, color, sort_order) VALUES (?, ?, ?, ?)",
            [
                (profile_id, "업무", "#6366f1", 0),
                (profile_id, "회의", "#8b5cf6", 1),
                (profile_id, "개인", "#10b981", 2),
                (profile_id, "기타", "#f59e0b", 3),
            ],
        )


# ── Sample data for new profiles (Item 1) ──
def _seed_sample_data(conn, profile_id: int):
    """Insert sample todos, event, and memo for new user onboarding."""
    today = date_mod.today()
    tomorrow = today + timedelta(days=1)
    conn.execute(
        "INSERT INTO todos (profile_id, title, priority, due_date, tags, sort_order) VALUES (?,?,?,?,?,?)",
        (profile_id, "My Planner 둘러보기", 1, today.isoformat(), '["시작"]', 1),
    )
    conn.execute(
        "INSERT INTO todos (profile_id, title, priority, due_date, tags, sort_order) VALUES (?,?,?,?,?,?)",
        (profile_id, "캘린더에 일정 추가해보기", 2, tomorrow.isoformat(), '["시작"]', 2),
    )
    conn.execute(
        "INSERT INTO todos (profile_id, title, priority, due_date, tags, sort_order) VALUES (?,?,?,?,?,?)",
        (profile_id, "집중 모드로 25분 작업하기", 2, tomorrow.isoformat(), '["시작"]', 3),
    )
    conn.execute(
        "INSERT INTO events (profile_id, title, start_time, color, memo) VALUES (?,?,?,?,?)",
        (profile_id, "My Planner 시작!", f"{today.isoformat()}T09:00", "#d97706", "환영합니다! 이 일정을 수정하거나 삭제해보세요."),
    )
    conn.execute(
        "INSERT INTO memos (profile_id, author, title, content) VALUES (?,?,?,?)",
        (profile_id, "My Planner", "환영합니다!", "## 시작 가이드\n\n- **할 일**: 좌측 메뉴에서 할 일을 관리하세요\n- **캘린더**: 일정을 한눈에 확인하세요\n- **집중 모드**: 포모도로 타이머로 생산성을 높이세요\n- **양식**: 13종의 업무 양식을 바로 사용하세요"),
    )


# ── Audit log helper ──
def _audit_log(conn, entity_type: str, entity_id: int, action: str, changes: dict = None, profile_id: str = None):
    """Insert a lightweight audit record."""
    conn.execute(
        "INSERT INTO audit_log (entity_type, entity_id, action, changes_json, profile_id) VALUES (?,?,?,?,?)",
        (entity_type, entity_id, action, json.dumps(changes or {}, ensure_ascii=False), profile_id),
    )


# ── Utility functions ──


def calc_dday(target_date_str: str) -> int:
    try:
        target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        return (target - date_mod.today()).days
    except (ValueError, TypeError):
        return 0


def redirect(request: Request, url: str):
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)







# ── Include common routers ──
from common.routers import memos as _r_memos, notices as _r_notices
from common.routers import worklogs as _r_worklogs, events as _r_events
from common.routers import todos as _r_todos, forms as _r_forms
from common.routers import settings as _r_settings, misc as _r_misc
from common.routers import sse as _r_sse
from common.routers import auth as _r_auth
from common.routers import notifications as _r_notifications

app.state.get_db = get_db
app.state.get_profile_id = get_profile_id
app.state.get_profile_name = get_profile_name
app.state.render = render
app.state.redirect = redirect
app.state.templates = templates
app.state.audit_log = _audit_log
app.state.event_bus = event_bus
app.state.base_dir = BASE_DIR
app.state.app_name = "my-planner"
app.state.gcal_client_id = GCAL_CLIENT_ID
app.state.worklog_img_dir = WORKLOG_IMG_DIR
app.state.get_categories = lambda conn, pid: conn.execute(
    "SELECT * FROM categories WHERE profile_id=? ORDER BY sort_order", (pid,)).fetchall()
app.state.get_network_group = get_network_group
app.state.profile_table = "profiles"
# Google OAuth config
app.state.auth_profile_table = "profiles"
app.state.auth_cookie_name = "planner_profile"
app.state.auth_cookie_max_age = 365 * 24 * 3600
app.state.ensure_default_categories = ensure_default_categories

app.include_router(_r_memos.router)
app.include_router(_r_notices.router)
app.include_router(_r_worklogs.router)
app.include_router(_r_events.router)
app.include_router(_r_todos.router)
app.include_router(_r_forms.router)
app.include_router(_r_settings.router)
app.include_router(_r_misc.router)
app.include_router(_r_sse.router)
app.include_router(_r_auth.router)
app.include_router(_r_notifications.router)



# ── Routes: Profile Setup ──
@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Show profile setup/select page. Redirect home if already logged in."""
    pid = get_profile_id(request)
    if pid:
        with get_db() as conn:
            row = conn.execute("SELECT id FROM profiles WHERE id=?", (pid,)).fetchone()
            if row:
                return RedirectResponse("/", status_code=303)
    return render(request, "setup.html", {"page": "setup", "profiles": []})


@app.post("/setup", response_class=HTMLResponse)
async def create_profile(request: Request, name: str = Form("")):
    """Create a new profile and set cookie."""
    name = clamp_text(fix_mojibake(name), 50).strip()
    if not name:
        name = "사용자"
    client_ip = get_client_ip(request)
    token = uuid.uuid4().hex + uuid.uuid4().hex

    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO profiles (name, token, last_ip) VALUES (?, ?, ?)",
            (name, token, client_ip),
        )
        profile_id = cursor.lastrowid
        ensure_default_categories(conn, profile_id)
        _seed_sample_data(conn, profile_id)

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "planner_profile", token,
        max_age=365 * 24 * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response


@app.post("/setup/select", response_class=HTMLResponse)
async def select_profile(request: Request):
    """Disabled — profile selection by ID is not allowed."""
    return RedirectResponse("/setup", status_code=303)


# ── Legacy redirects ──
@app.get("/profile", response_class=HTMLResponse)
async def profile_redirect(request: Request):
    return redirect(request, "/settings")


@app.post("/profile/logout", response_class=HTMLResponse)
async def logout_redirect(request: Request):
    return redirect(request, "/settings")


# ── Routes: Dashboard ──
def _gcal_redirect_uri(request: Request) -> str:
    return gcal_redirect_uri(request)


def _gcal_get_calendar_id(profile_id: int) -> str:
    """Get calendar_id for a profile from DB."""
    with get_db() as conn:
        row = conn.execute("SELECT calendar_id FROM gcal_tokens WHERE profile_id=?", (profile_id,)).fetchone()
    return row["calendar_id"] if row else "primary"


async def _gcal_refresh_token(profile_id: int) -> Optional[str]:
    with get_db() as conn:
        return await gcal_refresh_token(conn, profile_id)


async def _gcal_fetch_events(profile_id: int, time_min: str, time_max: str) -> list:
    token = await _gcal_refresh_token(profile_id)
    if not token:
        return []
    cal_id = _gcal_get_calendar_id(profile_id)
    return await gcal_fetch_events(token, cal_id, time_min, time_max)


async def _gcal_push_event(profile_id: int, title: str, start_time: str, end_time: str = "") -> str:
    """Create an event in Google Calendar. Returns the gcal event ID or empty string."""
    token = await _gcal_refresh_token(profile_id)
    if not token:
        return ""
    cal_id = _gcal_get_calendar_id(profile_id)
    return await gcal_push_event(token, cal_id, title, start_time, end_time)


async def _gcal_update_event(profile_id: int, gcal_id: str, title: str, start_time: str, end_time: str = ""):
    """Update an existing event in Google Calendar."""
    if not gcal_id:
        return
    token = await _gcal_refresh_token(profile_id)
    if not token:
        return
    cal_id = _gcal_get_calendar_id(profile_id)
    await gcal_update_event(token, cal_id, gcal_id, title, start_time, end_time)


async def _gcal_delete_event(profile_id: int, gcal_id: str):
    """Delete an event from Google Calendar."""
    if not gcal_id:
        return
    token = await _gcal_refresh_token(profile_id)
    if not token:
        return
    cal_id = _gcal_get_calendar_id(profile_id)
    await gcal_delete_event(token, cal_id, gcal_id)

app.state.gcal_fetch_events = _gcal_fetch_events
app.state.gcal_push_event = _gcal_push_event
app.state.gcal_update_event = _gcal_update_event
app.state.gcal_delete_event = _gcal_delete_event



def _run_automation_rules(conn, pid, today_str):
    rules = conn.execute(
        "SELECT * FROM automation_rules WHERE profile_id=? AND enabled=1", (pid,)
    ).fetchall()
    today_date = date_mod.today()
    for rule in rules:
        r = dict(rule)
        if r['last_run'] == today_str:
            continue
        tc = json.loads(r['trigger_config'])
        should_run = False
        if r['trigger_type'] == 'daily':
            should_run = True
        elif r['trigger_type'] == 'weekly':
            should_run = (today_date.weekday() == tc.get('weekday', 0))
        elif r['trigger_type'] == 'monthly':
            should_run = (today_date.day == tc.get('day', 1))
        if not should_run:
            continue
        ac = json.loads(r['action_config'])
        if r['action_type'] == 'create_todo':
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO todos (profile_id, title, description, priority, category_id, due_date, tags, sort_order) VALUES (?,?,?,?,?,?,?,?)",
                (pid, ac.get('title', ''), ac.get('description', ''),
                 ac.get('priority', 2), ac.get('category_id') or None,
                 today_str, ac.get('tags', ''), max_order + 1))
        conn.execute("UPDATE automation_rules SET last_run=? WHERE id=?", (today_str, r['id']))


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, plan_view: str = "week", plan_offset: int = 0, include_no_due: str = ""):
    pid = require_profile(request)
    today = date_mod.today()
    today_str = today.isoformat()
    _include_no_due = include_no_due == "1"

    with get_db() as conn:
        _run_automation_rules(conn, pid, today_str)
        week_start, week_end = get_week_range()
        stats = get_stats(conn, pid)

        today_todos = conn.execute("""
            SELECT t.*, c.name as category_name, c.color as category_color
            FROM todos t LEFT JOIN categories c ON t.category_id = c.id
            WHERE ((t.due_date <= ? AND t.completed = 0) OR (t.completed = 1 AND date(t.completed_at) = ?))
              AND t.profile_id = ?
            ORDER BY t.completed ASC, t.priority ASC, t.sort_order ASC
            LIMIT 10
        """, (today_str, today_str, pid)).fetchall()

        week_events = conn.execute("""
            SELECT e.*, c.name as category_name
            FROM events e LEFT JOIN categories c ON e.category_id = c.id
            WHERE date(e.start_time) BETWEEN ? AND ?
              AND e.profile_id = ?
            ORDER BY e.start_time ASC
            LIMIT 5
        """, (week_start.isoformat(), week_end.isoformat(), pid)).fetchall()

        recent_memos = conn.execute("""
            SELECT m.*, c.name as category_name, c.color as category_color
            FROM memos m LEFT JOIN categories c ON m.category_id = c.id
            WHERE m.profile_id = ? ORDER BY m.created_at DESC LIMIT 3
        """, (pid,)).fetchall()

        categories = conn.execute(
            "SELECT * FROM categories WHERE profile_id=? ORDER BY sort_order", (pid,)
        ).fetchall()

        project_progress = conn.execute("""
            SELECT c.name, c.color,
                   COUNT(CASE WHEN t.completed=0 THEN 1 END) as pending,
                   COUNT(CASE WHEN t.completed=1 THEN 1 END) as done,
                   COUNT(*) as total
            FROM categories c
            LEFT JOIN todos t ON t.category_id = c.id AND t.profile_id = ?
            WHERE c.profile_id = ?
            GROUP BY c.id HAVING total > 0
            ORDER BY c.sort_order
        """, (pid, pid)).fetchall()

        # Dashboard: today's work logs
        today_worklogs = conn.execute("""
            SELECT w.*, c.name as category_name, c.color as category_color
            FROM work_logs w LEFT JOIN categories c ON w.category_id = c.id
            WHERE w.profile_id = ? AND w.log_date = ?
            ORDER BY w.created_at DESC LIMIT 3
        """, (pid, today_str)).fetchall()

        today_worklogs_hours = conn.execute(
            "SELECT COALESCE(SUM(hours), 0) FROM work_logs WHERE profile_id=? AND log_date=?",
            (pid, today_str),
        ).fetchone()[0]

        # Dashboard: recent notices (same network group)
        network_group = get_network_group(request)
        recent_notices = conn.execute("""
            SELECT n.*, p.name as author_name
            FROM notices n LEFT JOIN profiles p ON n.profile_id = p.id
            WHERE n.network_group = ?
            ORDER BY n.pinned DESC, n.created_at DESC
            LIMIT 2
        """, (network_group,)).fetchall()

        tb_monday = today - timedelta(days=today.weekday())
        tb_sunday = tb_monday + timedelta(days=6)
        time_budgets_raw = conn.execute("""
            SELECT w.category_id, c.name, c.color, COALESCE(SUM(w.hours), 0) as used,
                   COALESCE(tb.weekly_hours, 0) as budget
            FROM work_logs w
            LEFT JOIN categories c ON w.category_id = c.id
            LEFT JOIN time_budgets tb ON tb.category_id = w.category_id AND tb.profile_id = ?
            WHERE w.profile_id = ? AND w.log_date >= ? AND w.log_date <= ?
            GROUP BY w.category_id
        """, (pid, pid, tb_monday.isoformat(), tb_sunday.isoformat())).fetchall()
        time_budgets = [dict(r) for r in time_budgets_raw]
        over_budget = [h for h in time_budgets if h["budget"] > 0 and h["used"] > h["budget"]]

        # Plan view data
        plan_data = {}
        if plan_view == "month":
            m = today.month + plan_offset
            y = today.year
            while m < 1:
                m += 12; y -= 1
            while m > 12:
                m -= 12; y += 1
            _, days_in_month = cal_mod.monthrange(y, m)
            month_start = date_mod(y, m, 1)
            month_end = date_mod(y, m, days_in_month)
            plan_todos = conn.execute("""
                SELECT t.*, c.name as category_name, c.color as category_color
                FROM todos t LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.due_date BETWEEN ? AND ? AND t.profile_id = ?
                ORDER BY t.due_date ASC, t.priority ASC, t.sort_order ASC
            """, (month_start.isoformat(), month_end.isoformat(), pid)).fetchall()
            start_weekday = month_start.weekday()
            cal_weeks = []
            current_week = [None] * start_weekday
            for day_num in range(1, days_in_month + 1):
                current_week.append(date_mod(y, m, day_num))
                if len(current_week) == 7:
                    cal_weeks.append(current_week); current_week = []
            if current_week:
                current_week += [None] * (7 - len(current_week))
                cal_weeks.append(current_week)
            todos_by_date: dict = {}
            for t in plan_todos:
                td = dict(t)
                dd = td.get("due_date", "")
                if dd:
                    todos_by_date.setdefault(dd, []).append(td)
            plan_data = {
                "cal_weeks": cal_weeks, "todos_by_date": todos_by_date,
                "nav_label": f"{y}년 {m}월", "reset_label": "이번달",
                "total_count": len(plan_todos),
                "done_count": sum(1 for t in plan_todos if t["completed"]),
                "weekday_names": WEEKDAY_NAMES,
            }
        else:
            monday = today - timedelta(days=today.weekday()) + timedelta(weeks=plan_offset)
            sunday = monday + timedelta(days=6)
            week_num = week_number_in_month(monday)
            if _include_no_due:
                plan_todos = conn.execute("""
                    SELECT t.*, c.name as category_name, c.color as category_color
                    FROM todos t LEFT JOIN categories c ON t.category_id = c.id
                    WHERE ((t.due_date BETWEEN ? AND ?) OR (t.due_date IS NULL OR t.due_date = ''))
                      AND t.profile_id = ?
                    ORDER BY t.due_date ASC, t.priority ASC, t.sort_order ASC
                """, (monday.isoformat(), sunday.isoformat(), pid)).fetchall()
            else:
                plan_todos = conn.execute("""
                    SELECT t.*, c.name as category_name, c.color as category_color
                    FROM todos t LEFT JOIN categories c ON t.category_id = c.id
                    WHERE t.due_date BETWEEN ? AND ? AND t.profile_id = ?
                    ORDER BY t.due_date ASC, t.priority ASC, t.sort_order ASC
                """, (monday.isoformat(), sunday.isoformat(), pid)).fetchall()
            week_days = []
            no_due_todos = [dict(t) for t in plan_todos if not t["due_date"]] if _include_no_due else []
            for i in range(7):
                d = monday + timedelta(days=i)
                day_todos = [dict(t) for t in plan_todos if t["due_date"] == d.isoformat()]
                # Attach no-due-date todos to today's column
                if _include_no_due and d == today:
                    day_todos.extend(no_due_todos)
                week_days.append({
                    "date": d, "date_str": d.isoformat(),
                    "label": f"{WEEKDAY_NAMES[i]} {d.month}/{d.day}",
                    "short_label": WEEKDAY_NAMES[i],
                    "is_today": d == today, "is_weekend": i >= 5,
                    "todos": day_todos,
                })
            plan_data = {
                "week_days": week_days,
                "nav_label": f"{monday.year}년 {monday.month}월 {week_num}주차 ({monday.strftime('%m.%d')} ~ {sunday.strftime('%m.%d')})",
                "reset_label": "오늘",
                "total_count": len(plan_todos),
                "done_count": sum(1 for t in plan_todos if t["completed"]),
            }

    return render(request, "dashboard.html", {
        "page": "dashboard",
        "stats": stats,
        "today_todos": [dict(r) for r in today_todos],
        "week_events": [dict(r) for r in week_events],
        "recent_memos": [dict(r) for r in recent_memos],
        "categories": [dict(r) for r in categories],
        "project_progress": [dict(r) for r in project_progress],
        "today_worklogs": [dict(r) for r in today_worklogs],
        "today_worklogs_hours": round(today_worklogs_hours, 1),
        "recent_notices": [dict(r) for r in recent_notices],
        "time_budgets": time_budgets,
        "over_budget": over_budget,
        "priority_map": PRIORITY_MAP,
        "plan_view": plan_view,
        "plan_offset": plan_offset,
        **plan_data,
    })


# ── Routes: Todos ──
















# ── Subtasks ──






# ── Routes: Todo Templates ──










# ── Routes: Automation Rules ──








# ── Routes: Calendar ──










# ── Routes: Google Calendar Event Edit/Delete ──

@app.get("/events/gcal/{gcal_id:path}/edit", response_class=HTMLResponse)
async def edit_gcal_event_form(request: Request, gcal_id: str):
    """Fetch a Google Calendar event and return an edit form."""
    pid = require_profile(request)
    import httpx
    token = await _gcal_refresh_token(pid)
    if not token:
        raise HTTPException(400, "Google Calendar not connected")
    with get_db() as conn:
        row = conn.execute("SELECT calendar_id FROM gcal_tokens WHERE profile_id=?", (pid,)).fetchone()
    cal_id = row["calendar_id"] if row else "primary"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GCAL_API_BASE}/calendars/{cal_id}/events/{gcal_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(404, "Event not found")
    ev = resp.json()
    # Parse start/end
    start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
    end = ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", ""))
    # Trim timezone offset for datetime-local input
    if "T" in start and "+" in start:
        start = start.rsplit("+", 1)[0]
    if "T" in end and "+" in end:
        end = end.rsplit("+", 1)[0]
    event_data = {
        "gcal_id": gcal_id,
        "title": ev.get("summary", ""),
        "start_time": start,
        "end_time": end,
        "memo": ev.get("description", ""),
        "color": "#4285F4",
    }
    return render(request, "partials/gcal_event_edit_form.html", {"event": event_data})


@app.put("/events/gcal/{gcal_id:path}", response_class=HTMLResponse)
async def update_gcal_event(request: Request, gcal_id: str,
                            title: str = Form(""),
                            start_time: str = Form(""),
                            end_time: str = Form(""),
                            memo: str = Form("")):
    pid = require_profile(request)
    title = clamp_text(fix_mojibake(title), 200)
    if not title or not start_time:
        return redirect(request, "/calendar")
    memo = clamp_text(fix_mojibake(memo), 2000)
    import httpx
    token = await _gcal_refresh_token(pid)
    if not token:
        raise HTTPException(400, "Google Calendar not connected")
    with get_db() as conn:
        row = conn.execute("SELECT calendar_id FROM gcal_tokens WHERE profile_id=?", (pid,)).fetchone()
    cal_id = row["calendar_id"] if row else "primary"
    body = {"summary": title, "description": memo}
    if "T" in start_time:
        body["start"] = {"dateTime": start_time + ":00+09:00" if len(start_time) == 16 else start_time, "timeZone": "Asia/Seoul"}
        if end_time and "T" in end_time:
            body["end"] = {"dateTime": end_time + ":00+09:00" if len(end_time) == 16 else end_time, "timeZone": "Asia/Seoul"}
        else:
            body["end"] = body["start"]
    else:
        body["start"] = {"date": start_time[:10]}
        body["end"] = {"date": (end_time[:10] if end_time else start_time[:10])}
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{GCAL_API_BASE}/calendars/{cal_id}/events/{gcal_id}",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    return redirect(request, "/calendar")


@app.delete("/events/gcal/{gcal_id:path}", response_class=HTMLResponse)
async def delete_gcal_event(request: Request, gcal_id: str):
    pid = require_profile(request)
    import httpx
    token = await _gcal_refresh_token(pid)
    if not token:
        raise HTTPException(400, "Google Calendar not connected")
    with get_db() as conn:
        row = conn.execute("SELECT calendar_id FROM gcal_tokens WHERE profile_id=?", (pid,)).fetchone()
    cal_id = row["calendar_id"] if row else "primary"
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{GCAL_API_BASE}/calendars/{cal_id}/events/{gcal_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return redirect(request, "/calendar")


# ── Routes: Memos ──












# ── Routes: Settings ──


@app.post("/settings/profile", response_class=HTMLResponse)
async def settings_update_profile(request: Request, name: str = Form("")):
    pid = require_profile(request)
    name = clamp_text(fix_mojibake(name), 50).strip()
    if not name:
        name = "사용자"
    with get_db() as conn:
        conn.execute("UPDATE profiles SET name=? WHERE id=?", (name, pid))
    return redirect(request, "/settings")










@app.post("/settings/background", response_class=HTMLResponse)
async def settings_background(request: Request):
    """Save background setting."""
    pid = require_profile(request)
    form = await request.form()
    bg_type = str(form.get("type", "none"))
    preset = str(form.get("preset", ""))
    opacity = float(form.get("opacity", 0.7))
    opacity = max(0.3, min(0.95, opacity))
    image_path = ""

    if bg_type not in ("preset", "upload", "none"):
        bg_type = "none"

    if bg_type == "upload":
        file: UploadFile = form.get("file")
        if file and file.filename:
            # Validate file
            ext = Path(file.filename).suffix.lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                raise HTTPException(400, "지원하지 않는 파일 형식입니다 (jpg/png/webp만 허용)")
            content = await file.read()
            if len(content) > 5 * 1024 * 1024:
                raise HTTPException(400, "파일 크기가 5MB를 초과합니다")
            # Save file
            filename = f"bg_{pid}_{uuid.uuid4().hex[:8]}{ext}"
            (BG_DIR / filename).write_bytes(content)
            image_path = f"/backgrounds/{filename}"
            # Clean up old background image if exists
            try:
                with get_db() as conn:
                    old = conn.execute(
                        "SELECT value FROM user_settings WHERE profile_id=? AND key='background'",
                        (pid,),
                    ).fetchone()
                    if old and old["value"]:
                        old_data = json.loads(old["value"])
                        old_img = old_data.get("image", "")
                        if old_img and old_img.startswith("/backgrounds/"):
                            old_file = BG_DIR / Path(old_img).name
                            if old_file.exists():
                                old_file.unlink()
            except Exception:
                pass
        else:
            # Keep existing image if no new file uploaded
            existing = get_bg_setting(pid)
            image_path = existing.get("image", "")
            if not image_path:
                bg_type = "none"

    setting = json.dumps({
        "type": bg_type,
        "preset": preset if bg_type == "preset" else "",
        "image": image_path if bg_type == "upload" else "",
        "opacity": opacity,
    })
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (profile_id, key, value) VALUES (?, 'background', ?)",
            (pid, setting),
        )
    return redirect(request, "/settings")


@app.get("/api/settings/background")
async def api_get_background(request: Request):
    """Return current background setting as JSON."""
    pid = require_profile(request)
    return JSONResponse(get_bg_setting(pid))


@app.post("/settings/logout", response_class=HTMLResponse)
async def settings_logout(request: Request):
    """Clear profile cookie."""
    response = RedirectResponse("/setup", status_code=303)
    response.delete_cookie("planner_profile")
    return response


# ── Routes: Backup & Restore ──




# ── Routes: Google Calendar OAuth ──
@app.get("/settings/gcal/connect")
async def gcal_connect(request: Request):
    if not GCAL_CLIENT_ID:
        raise HTTPException(400, "GCAL_CLIENT_ID 환경변수가 설정되지 않았습니다")
    from urllib.parse import urlencode
    pid = require_profile(request)
    params = urlencode({
        "client_id": GCAL_CLIENT_ID,
        "redirect_uri": _gcal_redirect_uri(request),
        "response_type": "code",
        "scope": GCAL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": str(pid),
    })
    return RedirectResponse(f"{GCAL_AUTH_URL}?{params}")


@app.get("/settings/gcal/callback")
async def gcal_callback(request: Request, code: str = "", error: str = "", state: str = ""):
    import logging
    logger = logging.getLogger("gcal")
    logger.info(f"[GCAL] callback: code={'yes' if code else 'NO'}, error={error}, state={state}")
    if error:
        logger.error(f"[GCAL] Google returned error: {error}")
        raise HTTPException(400, f"Google 인증 오류: {error}")
    if not code:
        logger.error("[GCAL] No code received")
        raise HTTPException(400, "Google 인증 코드가 없습니다")
    import httpx
    pid = int(state) if state.isdigit() else require_profile(request)
    redirect_uri = _gcal_redirect_uri(request)
    logger.info(f"[GCAL] token exchange: pid={pid}, redirect_uri={redirect_uri}")
    async with httpx.AsyncClient() as client:
        resp = await client.post(GCAL_TOKEN_URL, data={
            "code": code,
            "client_id": GCAL_CLIENT_ID,
            "client_secret": GCAL_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
    if resp.status_code != 200:
        logger.error(f"[GCAL] token exchange failed: {resp.status_code} {resp.text[:300]}")
        raise HTTPException(400, f"Google 토큰 교환 실패: {resp.text[:200]}")
    data = resp.json()
    logger.info(f"[GCAL] token received, expires_in={data.get('expires_in')}")
    expiry = (datetime.now() + timedelta(seconds=data["expires_in"])).isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO gcal_tokens (profile_id, access_token, refresh_token, token_expiry)
            VALUES (?, ?, ?, ?)
        """, (pid, data["access_token"], data.get("refresh_token", ""), expiry))
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/gcal/disconnect")
async def gcal_disconnect(request: Request):
    pid = require_profile(request)
    with get_db() as conn:
        conn.execute("DELETE FROM gcal_tokens WHERE profile_id=?", (pid,))
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/gcal/calendar-id")
async def gcal_set_calendar_id(request: Request, calendar_id: str = Form("primary")):
    pid = require_profile(request)
    with get_db() as conn:
        conn.execute("UPDATE gcal_tokens SET calendar_id=? WHERE profile_id=?", (calendar_id, pid))
    return RedirectResponse("/settings", status_code=303)


@app.get("/api/gcal/calendars")
async def gcal_list_calendars(request: Request):
    import httpx
    pid = require_profile(request)
    token = await _gcal_refresh_token(pid)
    if not token:
        return JSONResponse([])
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GCAL_API_BASE}/users/me/calendarList",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        return JSONResponse([])
    items = resp.json().get("items", [])
    return JSONResponse([{"id": c["id"], "summary": c.get("summary", c["id"])} for c in items])


# ── Routes: Work Logs ──












# ── Routes: Notices ──












# ── Routes: Form Templates (양식) ──




















# ── Routes: Form Entries (양식 작성) ──












# ── Data Export (CSV / Excel) ──
def _collect_export_data(conn, tpl_id, pid, date=None):
    tpl = conn.execute("SELECT * FROM form_templates WHERE id=? AND profile_id IN (?, 0)", (tpl_id, pid)).fetchone()
    if not tpl:
        return None, None, None
    fields = json.loads(tpl["fields"])
    where = "template_id=? AND profile_id=?"
    params = [tpl_id, pid]
    if date:
        where += " AND entry_date=?"
        params.append(date)
    entries = conn.execute(f"SELECT * FROM form_entries WHERE {where} ORDER BY entry_date, id", params).fetchall()
    return tpl, fields, entries




# ── iCal Feed (Calendar Subscription) ──


# ── Routes: Audit Log ──


# ── Global Search ──


# ── Focus mode ──


# ── Routes: Plans ──


# ── Quick-add from dashboard ──


# ── Routes: Shared Files ──
def _get_group_dir(network_group: str) -> Path:
    """Get the shared directory for a network group, creating it if needed."""
    safe_group = network_group.replace(".", "_")
    group_dir = SHARED_DIR / safe_group
    group_dir.mkdir(parents=True, exist_ok=True)
    return group_dir


def _generate_unique_filename(original: str) -> str:
    """Generate a unique filename preserving extension, sanitized against path traversal."""
    stem = Path(original).name  # strip directory components
    stem = Path(stem).stem
    stem = stem.replace("..", "").replace("/", "").replace("\\", "").strip(". ")
    if not stem:
        stem = "file"
    ext = Path(original).suffix
    unique = uuid.uuid4().hex[:8]
    return f"{stem}_{unique}{ext}"


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}
PDF_EXTENSIONS = {".pdf"}


@app.get("/files", response_class=HTMLResponse)
async def files_page(request: Request):
    pid = require_profile(request)
    network_group = get_network_group(request)
    group_dir = _get_group_dir(network_group)

    with get_db() as conn:
        files = conn.execute("""
            SELECT sf.*, p.name as uploader_name
            FROM shared_files sf
            LEFT JOIN profiles p ON sf.uploader_profile_id = p.id
            WHERE sf.network_group = ?
            ORDER BY sf.uploaded_at DESC
        """, (network_group,)).fetchall()

    file_list = []
    for f in files:
        fd = dict(f)
        ext = Path(fd["original_name"]).suffix.lower()
        fd["is_image"] = ext in IMAGE_EXTENSIONS
        fd["is_pdf"] = ext in PDF_EXTENSIONS
        fd["previewable"] = fd["is_image"] or fd["is_pdf"]
        fd["can_delete"] = (fd["uploader_profile_id"] == pid)
        # Icon
        if fd["is_image"]:
            fd["icon"] = "🖼️"
        elif fd["is_pdf"]:
            fd["icon"] = "📄"
        elif ext in {".doc", ".docx"}:
            fd["icon"] = "📝"
        elif ext in {".xls", ".xlsx"}:
            fd["icon"] = "📊"
        elif ext in {".zip", ".tar", ".gz", ".rar"}:
            fd["icon"] = "📦"
        elif ext in {".mp4", ".avi", ".mov", ".mkv"}:
            fd["icon"] = "🎬"
        else:
            fd["icon"] = "📎"
        file_list.append(fd)

    return render(request, "files.html", {
        "page": "files",
        "files": file_list,
        "network_group": network_group,
        "client_ip": get_client_ip(request),
    })


@app.post("/files", response_class=HTMLResponse)
async def upload_files(request: Request, files: list[UploadFile] = File(...)):
    pid = require_profile(request)
    network_group = get_network_group(request)
    group_dir = _get_group_dir(network_group)

    uploaded_count = 0
    with get_db() as conn:
        for upload_file in files:
            if not upload_file.filename:
                continue

            # Read file content
            content = await upload_file.read()
            if len(content) > MAX_FILE_SIZE:
                continue  # Skip files over 50MB
            if len(content) == 0:
                continue

            original_name = upload_file.filename
            stored_name = _generate_unique_filename(original_name)
            file_path = group_dir / stored_name

            with open(file_path, "wb") as f:
                f.write(content)

            conn.execute("""
                INSERT INTO shared_files (filename, original_name, uploader_profile_id, network_group, file_size)
                VALUES (?, ?, ?, ?, ?)
            """, (stored_name, original_name, pid, network_group, len(content)))
            uploaded_count += 1

    return redirect(request, "/files")


@app.get("/files/download/{file_id}", response_class=HTMLResponse)
async def download_file(request: Request, file_id: int):
    pid = require_profile(request)
    network_group = get_network_group(request)

    with get_db() as conn:
        f = conn.execute(
            "SELECT * FROM shared_files WHERE id=? AND network_group=?",
            (file_id, network_group),
        ).fetchone()

    if not f:
        raise HTTPException(404, detail="File not found")

    group_dir = _get_group_dir(network_group)
    file_path = group_dir / f["filename"]
    if not file_path.exists():
        raise HTTPException(404, detail="File not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=f["original_name"],
        media_type="application/octet-stream",
    )


@app.get("/files/preview/{file_id}")
async def preview_file(request: Request, file_id: int):
    pid = require_profile(request)
    network_group = get_network_group(request)

    with get_db() as conn:
        f = conn.execute(
            "SELECT * FROM shared_files WHERE id=? AND network_group=?",
            (file_id, network_group),
        ).fetchone()

    if not f:
        raise HTTPException(404)

    group_dir = _get_group_dir(network_group)
    file_path = group_dir / f["filename"]
    if not file_path.exists():
        raise HTTPException(404)

    ext = Path(f["original_name"]).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        media_types = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
            ".bmp": "image/bmp",
        }
        return FileResponse(str(file_path), media_type=media_types.get(ext, "application/octet-stream"))
    elif ext in PDF_EXTENSIONS:
        return FileResponse(str(file_path), media_type="application/pdf")
    else:
        raise HTTPException(400, detail="Preview not supported for this file type")


@app.delete("/files/{file_id}", response_class=HTMLResponse)
async def delete_file(request: Request, file_id: int):
    pid = require_profile(request)
    network_group = get_network_group(request)

    with get_db() as conn:
        f = conn.execute(
            "SELECT * FROM shared_files WHERE id=? AND network_group=?",
            (file_id, network_group),
        ).fetchone()

        if not f:
            raise HTTPException(404)

        # Only uploader can delete
        if f["uploader_profile_id"] != pid:
            raise HTTPException(403, detail="Only the uploader can delete this file")

        # Delete from disk
        group_dir = _get_group_dir(network_group)
        file_path = group_dir / f["filename"]
        if file_path.exists():
            file_path.unlink()

        conn.execute("DELETE FROM shared_files WHERE id=?", (file_id,))

    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return redirect(request, "/files")


# ── Reminders API ──


# ── Service Worker (root scope) ──


# ── Routes: D-day ──
@app.get("/ddays", response_class=HTMLResponse)
async def ddays_page(request: Request):
    pid = require_profile(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ddays WHERE profile_id=? ORDER BY target_date ASC", (pid,)
        ).fetchall()
    ddays = []
    for r in rows:
        d = dict(r)
        d["dday"] = calc_dday(d["target_date"])
        if not d.get("icon"):
            d["icon"] = "\U0001f3af"
        ddays.append(d)
    return render(request, "ddays.html", {"page": "ddays", "ddays": ddays})


@app.post("/ddays", response_class=HTMLResponse)
async def create_dday(request: Request, title: str = Form(""), target_date: str = Form(""), icon: str = Form("\U0001f3af")):
    pid = require_profile(request)
    if not title or not target_date:
        return redirect(request, "/ddays")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO ddays (profile_id, title, target_date, icon) VALUES (?,?,?,?)",
            (pid, title, target_date, icon or "\U0001f3af"),
        )
    return redirect(request, "/ddays")


@app.delete("/ddays/{dday_id}", response_class=HTMLResponse)
async def delete_dday(request: Request, dday_id: int):
    pid = require_profile(request)
    with get_db() as conn:
        conn.execute("DELETE FROM ddays WHERE id=? AND profile_id=?", (dday_id, pid))
    return HTMLResponse("")


# ── Routes: Links ──
@app.get("/links", response_class=HTMLResponse)
async def links_page(request: Request):
    pid = require_profile(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM links WHERE profile_id=? ORDER BY created_at DESC", (pid,)
        ).fetchall()
        cats = conn.execute(
            "SELECT DISTINCT category FROM links WHERE profile_id=? AND category != '' ORDER BY category",
            (pid,),
        ).fetchall()
    links = [dict(r) for r in rows]
    categories = [r["category"] for r in cats]
    return render(request, "links.html", {
        "page": "links",
        "links": links,
        "link_categories": categories,
    })


@app.post("/links", response_class=HTMLResponse)
async def create_link(request: Request, title: str = Form(""), url: str = Form(""),
                      category: str = Form(""), description: str = Form("")):
    pid = require_profile(request)
    if not title or not url:
        return redirect(request, "/links")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO links (profile_id, title, url, category, description) VALUES (?,?,?,?,?)",
            (pid, title, url, category, description),
        )
    return redirect(request, "/links")


@app.delete("/links/{link_id}", response_class=HTMLResponse)
async def delete_link(request: Request, link_id: int):
    pid = require_profile(request)
    with get_db() as conn:
        conn.execute("DELETE FROM links WHERE id=? AND profile_id=?", (link_id, pid))
    return HTMLResponse("")


# ── Routes: Stats ──
@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    pid = require_profile(request)
    with get_db() as conn:
        stats = get_stats(conn, pid)
        chart_data = get_weekly_chart_data(conn, pid)

        total_all = conn.execute("SELECT COUNT(*) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
        total_completed = conn.execute("SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=1", (pid,)).fetchone()[0]
        total_rate = round(total_completed / total_all * 100) if total_all > 0 else 0

        cat_stats = []
        cats = conn.execute("SELECT * FROM categories WHERE profile_id=? ORDER BY sort_order", (pid,)).fetchall()
        for c in cats:
            total = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE category_id=? AND profile_id=?", (c["id"], pid)
            ).fetchone()[0]
            done = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE category_id=? AND profile_id=? AND completed=1", (c["id"], pid)
            ).fetchone()[0]
            cat_stats.append({"name": c["name"], "color": c["color"], "total": total, "done": done})

        monthly_data = []
        today = date_mod.today()
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            while m < 1:
                m += 12
                y -= 1
            label = f"{y}-{m:02d}"
            month_start = f"{y}-{m:02d}-01"
            if m == 12:
                month_end = f"{y + 1}-01-01"
            else:
                month_end = f"{y}-{m + 1:02d}-01"
            total = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE profile_id=? AND created_at>=? AND created_at<?",
                (pid, month_start, month_end),
            ).fetchone()[0]
            done = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=1 AND completed_at>=? AND completed_at<?",
                (pid, month_start, month_end),
            ).fetchone()[0]
            monthly_data.append({"label": label, "total": total, "done": done})

        monthly_events = conn.execute("""
            SELECT strftime('%Y-%m', start_time) as m, COUNT(*) as c
            FROM events WHERE profile_id=?
            AND start_time >= date('now', 'start of year', 'localtime')
            GROUP BY m ORDER BY m
        """, (pid,)).fetchall()

        year_ago = (date_mod.today() - timedelta(days=364)).isoformat()
        heatmap_data = conn.execute(
            "SELECT date(completed_at) as d, COUNT(*) as cnt FROM todos "
            "WHERE profile_id=? AND completed=1 AND completed_at>=? "
            "GROUP BY date(completed_at) ORDER BY d",
            (pid, year_ago)
        ).fetchall()
        heatmap = {row["d"]: row["cnt"] for row in heatmap_data if row["d"]}

    return render(request, "stats.html", {
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
        "heatmap_today": date_mod.today().isoformat(),
    })


# ── Routes: Form Entry Stats (JSON) ──


# ── Review ──


# ── Health check ──



# ── QR Code Access ──

@app.get("/api/qr-code")
async def my_qr_code_api(request: Request):
    import qrcode, io as _io, base64
    host = request.headers.get("host", "localhost:8003")
    scheme = "https" if request.url.scheme == "https" or "fly.dev" in host else "http"
    token = request.cookies.get("planner_profile", "")
    url = f"{scheme}://{host}/sync-profile?token={token}" if token else f"{scheme}://{host}"
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return JSONResponse({"qr_base64": b64, "url": url})

@app.get("/sync-profile")
async def my_sync_profile(request: Request, token: str = ""):
    if not token:
        return RedirectResponse("/setup", status_code=303)
    with get_db() as conn:
        row = conn.execute("SELECT id, name FROM profiles WHERE token=?", (token,)).fetchone()
    if not row:
        return RedirectResponse("/setup", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "planner_profile", token,
        max_age=365 * 24 * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response


# ══════════════════════════════════════════════════════════════════════
# Item 8: Habits Tracker
# ══════════════════════════════════════════════════════════════════════

@app.get("/habits", response_class=HTMLResponse)
async def habits_page(request: Request):
    pid = require_profile(request)
    today = date_mod.today()
    today_str = today.isoformat()
    with get_db() as conn:
        habits = conn.execute(
            "SELECT * FROM habits WHERE profile_id=? AND archived=0 ORDER BY sort_order", (pid,)
        ).fetchall()
        start_date = (today - timedelta(days=29)).isoformat()
        logs = conn.execute(
            "SELECT habit_id, log_date, log_time, count FROM habit_logs WHERE profile_id=? AND log_date>=?",
            (pid, start_date),
        ).fetchall()
        # Today's logs with counts for counter/time habits
        today_logs = conn.execute(
            "SELECT habit_id, log_time, count FROM habit_logs WHERE profile_id=? AND log_date=?",
            (pid, today_str),
        ).fetchall()
        # Weekly logs for weekly habits
        week_start = (today - timedelta(days=today.weekday())).isoformat()
        week_logs = conn.execute(
            "SELECT habit_id, log_date FROM habit_logs WHERE profile_id=? AND log_date>=? AND log_date<=?",
            (pid, week_start, today_str),
        ).fetchall()
    logs_set = {(r["habit_id"], r["log_date"]) for r in logs}
    # Count today's completions per habit
    today_counts = {}
    today_time_checks = {}
    for r in today_logs:
        hid = r["habit_id"]
        today_counts[hid] = today_counts.get(hid, 0) + (r["count"] or 1)
        if r["log_time"]:
            today_time_checks.setdefault(hid, set()).add(r["log_time"])
    # Weekly completions per habit
    week_counts = {}
    for r in week_logs:
        hid = r["habit_id"]
        week_counts[hid] = week_counts.get(hid, 0) + 1

    habits_data = []
    for h in habits:
        hd = dict(h)
        hd["frequency_detail_parsed"] = json.loads(hd["frequency_detail"]) if hd.get("frequency_detail") else None
        hd["target_count"] = hd.get("target_count") or 1

        # Determine tracking type
        fd = hd["frequency_detail_parsed"]
        if fd:
            hd["tracking_type"] = fd.get("type", "daily")
        else:
            hd["tracking_type"] = "daily"

        # Today progress
        hd["today_count"] = today_counts.get(hd["id"], 0)
        hd["today_time_checks"] = today_time_checks.get(hd["id"], set())
        hd["week_count"] = week_counts.get(hd["id"], 0)

        # Streak calculation
        streak = 0
        d = today
        while True:
            if (hd["id"], d.isoformat()) in logs_set:
                streak += 1
                d -= timedelta(days=1)
            else:
                break
        hd["streak"] = streak

        # Today done check depends on tracking type
        if hd["tracking_type"] == "times_per_day":
            hd["today_done"] = hd["today_count"] >= hd["target_count"]
        elif hd["tracking_type"] == "specific_times":
            times = fd.get("times", []) if fd else []
            hd["today_done"] = len(hd["today_time_checks"]) >= len(times)
            hd["specific_times"] = times
        elif hd["tracking_type"] == "every_n_hours":
            hd["today_done"] = hd["today_count"] >= hd["target_count"]
        elif hd["tracking_type"] == "times_per_week":
            weekly_target = fd.get("count", 3) if fd else 3
            hd["today_done"] = hd["week_count"] >= weekly_target
            hd["weekly_target"] = weekly_target
        else:
            hd["today_done"] = (hd["id"], today_str) in logs_set

        habits_data.append(hd)
    dates = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    return render(request, "habits.html", {
        "page": "habits", "habits": habits_data,
        "logs_set": logs_set, "dates": dates, "today_str": today_str,
    })


@app.post("/habits", response_class=HTMLResponse)
async def create_habit(request: Request):
    pid = require_profile(request)
    form = await request.form()
    name = clamp_text(fix_mojibake(form.get("name", "")), 50).strip()
    if not name:
        return redirect(request, "/habits")
    icon = form.get("icon", "✅") or "✅"
    color = form.get("color", "#6366f1")
    # New time-based fields
    tracking_type = form.get("tracking_type", "daily")  # daily, counter, interval, specific, weekly
    target_count = int(form.get("target_count", "1") or "1")
    reminder_enabled = form.get("reminder_enabled", "")

    frequency_detail = None
    reminder_times = None

    if tracking_type == "counter":
        frequency_detail = json.dumps({"type": "times_per_day", "count": target_count})
    elif tracking_type == "interval":
        interval_hours = int(form.get("interval_hours", "2") or "2")
        start_time = form.get("interval_start", "08:00") or "08:00"
        end_time = form.get("interval_end", "22:00") or "22:00"
        frequency_detail = json.dumps({"type": "every_n_hours", "interval": interval_hours, "start": start_time, "end": end_time})
        # Auto-generate reminder times
        if reminder_enabled:
            times = []
            sh, sm = int(start_time.split(":")[0]), int(start_time.split(":")[1])
            eh = int(end_time.split(":")[0])
            current_h, current_m = sh, sm
            while current_h < eh or (current_h == eh and current_m == 0):
                times.append(f"{current_h:02d}:{current_m:02d}")
                current_h += interval_hours
            reminder_times = json.dumps(times)
    elif tracking_type == "specific":
        times_raw = form.getlist("specific_times")
        times = [t for t in times_raw if t]
        if times:
            frequency_detail = json.dumps({"type": "specific_times", "times": times})
            target_count = len(times)
            if reminder_enabled:
                reminder_times = json.dumps(times)
    elif tracking_type == "weekly":
        weekly_count = int(form.get("weekly_count", "3") or "3")
        frequency_detail = json.dumps({"type": "times_per_week", "count": weekly_count})
        target_count = weekly_count
    else:
        # daily - default
        target_count = 1
        if reminder_enabled:
            rt = form.get("reminder_time", "")
            if rt:
                reminder_times = json.dumps([rt])

    with get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM habits WHERE profile_id=?", (pid,)).fetchone()[0]
        conn.execute(
            "INSERT INTO habits (profile_id, name, icon, color, sort_order, target_count, frequency_detail, reminder_times) VALUES (?,?,?,?,?,?,?,?)",
            (pid, name, icon, color, max_order + 1, target_count, frequency_detail, reminder_times),
        )
    return redirect(request, "/habits")


@app.post("/habits/{habit_id}/toggle", response_class=HTMLResponse)
async def toggle_habit(request: Request, habit_id: int):
    pid = require_profile(request)
    form = await request.form()
    log_date = form.get("date", "") or date_mod.today().isoformat()
    log_time = form.get("log_time", "") or None  # For time-based habits
    action = form.get("action", "toggle")  # toggle, increment, decrement

    with get_db() as conn:
        habit = conn.execute("SELECT * FROM habits WHERE id=? AND profile_id=?", (habit_id, pid)).fetchone()
        if not habit:
            return redirect(request, "/habits")

        fd = json.loads(habit["frequency_detail"]) if habit["frequency_detail"] else None
        tracking_type = fd.get("type", "daily") if fd else "daily"

        if tracking_type in ("times_per_day", "every_n_hours") and action in ("increment", "toggle"):
            # Counter mode: add a log entry (multiple per day allowed)
            counter_time = datetime.now().strftime("%H:%M:%S")
            if action == "toggle":
                count_today = conn.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM habit_logs WHERE habit_id=? AND log_date=?",
                    (habit_id, log_date)
                ).fetchone()[0]
                target = habit["target_count"] or 1
                if count_today >= target:
                    last = conn.execute(
                        "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? ORDER BY id DESC LIMIT 1",
                        (habit_id, log_date)
                    ).fetchone()
                    if last:
                        conn.execute("DELETE FROM habit_logs WHERE id=?", (last["id"],))
                else:
                    conn.execute(
                        "INSERT INTO habit_logs (habit_id, profile_id, log_date, log_time, count) VALUES (?,?,?,?,1)",
                        (habit_id, pid, log_date, counter_time),
                    )
            elif action == "increment":
                conn.execute(
                    "INSERT INTO habit_logs (habit_id, profile_id, log_date, log_time, count) VALUES (?,?,?,?,1)",
                    (habit_id, pid, log_date, counter_time),
                )
        elif tracking_type == "specific_times" and log_time:
            # Time-specific: toggle specific time slot
            existing = conn.execute(
                "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? AND log_time=?",
                (habit_id, log_date, log_time)
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM habit_logs WHERE id=?", (existing["id"],))
            else:
                conn.execute(
                    "INSERT INTO habit_logs (habit_id, profile_id, log_date, log_time, count) VALUES (?,?,?,?,1)",
                    (habit_id, pid, log_date, log_time),
                )
        elif action == "decrement":
            last = conn.execute(
                "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? ORDER BY id DESC LIMIT 1",
                (habit_id, log_date)
            ).fetchone()
            if last:
                conn.execute("DELETE FROM habit_logs WHERE id=?", (last["id"],))
        else:
            # Standard daily toggle
            existing = conn.execute(
                "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? AND log_time IS NULL",
                (habit_id, log_date)
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM habit_logs WHERE id=?", (existing["id"],))
            else:
                conn.execute(
                    "INSERT INTO habit_logs (habit_id, profile_id, log_date, count) VALUES (?,?,?,1)",
                    (habit_id, pid, log_date),
                )
    return redirect(request, "/habits")


@app.post("/habits/{habit_id}/increment", response_class=HTMLResponse)
async def increment_habit(request: Request, habit_id: int):
    """Quick increment for counter-type habits (HTMX)."""
    pid = require_profile(request)
    log_date = date_mod.today().isoformat()
    log_time = datetime.now().strftime("%H:%M:%S")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO habit_logs (habit_id, profile_id, log_date, log_time, count) VALUES (?,?,?,?,1)",
            (habit_id, pid, log_date, log_time),
        )
    return redirect(request, "/habits")


@app.post("/habits/{habit_id}/decrement", response_class=HTMLResponse)
async def decrement_habit(request: Request, habit_id: int):
    """Quick decrement for counter-type habits (HTMX)."""
    pid = require_profile(request)
    log_date = date_mod.today().isoformat()
    with get_db() as conn:
        last = conn.execute(
            "SELECT id FROM habit_logs WHERE habit_id=? AND log_date=? ORDER BY id DESC LIMIT 1",
            (habit_id, log_date)
        ).fetchone()
        if last:
            conn.execute("DELETE FROM habit_logs WHERE id=?", (last["id"],))
    return redirect(request, "/habits")


@app.delete("/habits/{habit_id}", response_class=HTMLResponse)
async def delete_habit(request: Request, habit_id: int):
    pid = require_profile(request)
    with get_db() as conn:
        conn.execute("DELETE FROM habits WHERE id=? AND profile_id=?", (habit_id, pid))
    return HTMLResponse("")


# ══════════════════════════════════════════════════════════════════════
# Item 9: Onboarding Checklist API
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/onboarding")
async def get_onboarding(request: Request):
    pid = require_profile(request)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM onboarding_progress WHERE profile_id=?", (pid,)).fetchone()
        if not row:
            conn.execute("INSERT INTO onboarding_progress (profile_id) VALUES (?)", (pid,))
            return JSONResponse({"step1": False, "step2": False, "step3": False, "step4": False, "dismissed": False})
        return JSONResponse({
            "step1": bool(row["step1_done"]), "step2": bool(row["step2_done"]),
            "step3": bool(row["step3_done"]), "step4": bool(row["step4_done"]),
            "dismissed": bool(row["dismissed"]),
        })


@app.post("/api/onboarding/step/{step}")
async def complete_onboarding_step(request: Request, step: int):
    pid = require_profile(request)
    if step not in (1, 2, 3, 4):
        raise HTTPException(400)
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO onboarding_progress (profile_id) VALUES (?)", (pid,))
        conn.execute(f"UPDATE onboarding_progress SET step{step}_done=1 WHERE profile_id=?", (pid,))
    return JSONResponse({"ok": True})


@app.post("/api/onboarding/dismiss")
async def dismiss_onboarding(request: Request):
    pid = require_profile(request)
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO onboarding_progress (profile_id) VALUES (?)", (pid,))
        conn.execute("UPDATE onboarding_progress SET dismissed=1 WHERE profile_id=?", (pid,))
    return JSONResponse({"ok": True})


# ══════════════════════════════════════════════════════════════════════
# Item 10: Morning Brief API
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/morning-brief")
async def morning_brief(request: Request):
    pid = require_profile(request)
    today = date_mod.today().isoformat()
    with get_db() as conn:
        todo_count = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE profile_id=? AND due_date<=? AND completed=0", (pid, today)
        ).fetchone()[0]
        event_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE profile_id=? AND date(start_time)=?", (pid, today)
        ).fetchone()[0]
        habits_total = conn.execute(
            "SELECT COUNT(*) FROM habits WHERE profile_id=? AND archived=0", (pid,)
        ).fetchone()[0]
        habits_done = conn.execute(
            "SELECT COUNT(*) FROM habit_logs WHERE profile_id=? AND log_date=?", (pid, today)
        ).fetchone()[0]
    return JSONResponse({
        "date": today,
        "todos_pending": todo_count,
        "events_today": event_count,
        "habits_total": habits_total,
        "habits_done": habits_done,
        "message": f"오늘 할 일 {todo_count}개, 일정 {event_count}개가 있습니다.",
    })


@app.post("/api/morning-brief/settings")
async def save_morning_brief_settings(request: Request, enabled: int = Form(0), hour: int = Form(8), minute: int = Form(0)):
    pid = require_profile(request)
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO morning_brief_settings (profile_id, enabled, hour, minute) VALUES (?,?,?,?)",
            (pid, enabled, max(0, min(23, hour)), max(0, min(59, minute))),
        )
    return JSONResponse({"ok": True})


@app.get("/api/morning-brief/settings")
async def get_morning_brief_settings(request: Request):
    pid = require_profile(request)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM morning_brief_settings WHERE profile_id=?", (pid,)).fetchone()
    if not row:
        return JSONResponse({"enabled": False, "hour": 8, "minute": 0})
    return JSONResponse({"enabled": bool(row["enabled"]), "hour": row["hour"], "minute": row["minute"]})


# ══════════════════════════════════════════════════════════════════════
# Item 5: PWA Install Prompt API
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/pwa-install-dismissed")
async def pwa_install_dismissed(request: Request):
    pid = require_profile(request)
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (profile_id, key, value) VALUES (?, 'pwa_install_dismissed', '1')",
            (pid,),
        )
    return JSONResponse({"ok": True})


# ══════════════════════════════════════════════════════════════════════
# Item 17: Play Store Review Prompt
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/track-visit")
async def track_visit(request: Request):
    pid = require_profile(request)
    today = date_mod.today().isoformat()
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO app_visits (profile_id, visit_date) VALUES (?,?)", (pid, today))
    return JSONResponse({"ok": True})


@app.get("/api/review-prompt")
async def check_review_prompt(request: Request):
    pid = require_profile(request)
    today = date_mod.today()
    with get_db() as conn:
        # Check if already reviewed or snoozed
        snoozed = conn.execute(
            "SELECT value FROM user_settings WHERE profile_id=? AND key='review_snoozed_until'", (pid,)
        ).fetchone()
        if snoozed and snoozed["value"] and snoozed["value"] > today.isoformat():
            return JSONResponse({"show": False})
        reviewed = conn.execute(
            "SELECT value FROM user_settings WHERE profile_id=? AND key='review_done'", (pid,)
        ).fetchone()
        if reviewed:
            return JSONResponse({"show": False})
        # Check 7 consecutive days
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


@app.post("/api/review-prompt/dismiss")
async def dismiss_review_prompt(request: Request, action: str = Form("snooze")):
    pid = require_profile(request)
    with get_db() as conn:
        if action == "done":
            conn.execute(
                "INSERT OR REPLACE INTO user_settings (profile_id, key, value) VALUES (?, 'review_done', '1')", (pid,)
            )
        else:
            snooze_until = (date_mod.today() + timedelta(days=30)).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO user_settings (profile_id, key, value) VALUES (?, 'review_snoozed_until', ?)",
                (pid, snooze_until),
            )
    return JSONResponse({"ok": True})


# ══════════════════════════════════════════════════════════════════════
# Item 20: /today route — unified today view
# ══════════════════════════════════════════════════════════════════════

@app.get("/today", response_class=HTMLResponse)
async def today_view(request: Request):
    pid = require_profile(request)
    today = date_mod.today()
    today_str = today.isoformat()
    with get_db() as conn:
        todos = conn.execute("""
            SELECT t.*, c.name as category_name, c.color as category_color
            FROM todos t LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.profile_id=? AND ((t.due_date<=? AND t.completed=0) OR (t.completed=1 AND date(t.completed_at)=?))
            ORDER BY t.completed ASC, t.priority ASC, t.sort_order ASC
        """, (pid, today_str, today_str)).fetchall()
        events = conn.execute("""
            SELECT e.*, c.name as category_name
            FROM events e LEFT JOIN categories c ON e.category_id = c.id
            WHERE e.profile_id=? AND date(e.start_time)=?
            ORDER BY e.start_time ASC
        """, (pid, today_str)).fetchall()
        worklogs = conn.execute("""
            SELECT w.*, c.name as category_name, c.color as category_color
            FROM work_logs w LEFT JOIN categories c ON w.category_id = c.id
            WHERE w.profile_id=? AND w.log_date=?
            ORDER BY w.created_at DESC
        """, (pid, today_str)).fetchall()
        habits = conn.execute("SELECT * FROM habits WHERE profile_id=? AND archived=0 ORDER BY sort_order", (pid,)).fetchall()
        habit_logs_today = conn.execute(
            "SELECT habit_id FROM habit_logs WHERE profile_id=? AND log_date=?", (pid, today_str)
        ).fetchall()
    done_habits = {r["habit_id"] for r in habit_logs_today}
    habits_data = [dict(h) | {"today_done": h["id"] in done_habits} for h in habits]
    return render(request, "today.html", {
        "page": "today", "today_str": today_str,
        "todos": [dict(r) for r in todos],
        "events": [dict(r) for r in events],
        "worklogs": [dict(r) for r in worklogs],
        "habits": habits_data,
        "priority_map": PRIORITY_MAP,
    })


# ══════════════════════════════════════════════════════════════════════
# Item 13: Starter Automation Suggestions
# ══════════════════════════════════════════════════════════════════════

@app.post("/automations/apply-starter", response_class=HTMLResponse)
async def apply_starter_automation(request: Request, preset: str = Form("")):
    pid = require_profile(request)
    starters = {
        "weekly_review": {
            "name": "매주 금요일 주간 리뷰",
            "trigger_type": "weekly",
            "trigger_config": json.dumps({"weekday": 4}),
            "action_type": "create_todo",
            "action_config": json.dumps({"title": "주간 업무 리뷰 작성", "priority": 1}),
        },
        "daily_standup": {
            "name": "매일 오전 업무 정리",
            "trigger_type": "daily",
            "trigger_config": json.dumps({}),
            "action_type": "create_todo",
            "action_config": json.dumps({"title": "오늘의 업무 우선순위 정리", "priority": 2}),
        },
        "monthly_report": {
            "name": "매월 1일 월간 보고서",
            "trigger_type": "monthly",
            "trigger_config": json.dumps({"day": 1}),
            "action_type": "create_todo",
            "action_config": json.dumps({"title": "월간 업무 보고서 작성", "priority": 1}),
        },
    }
    if preset not in starters:
        return redirect(request, "/automations")
    s = starters[preset]
    with get_db() as conn:
        conn.execute(
            "INSERT INTO automation_rules (profile_id, name, trigger_type, trigger_config, action_type, action_config) VALUES (?,?,?,?,?,?)",
            (pid, s["name"], s["trigger_type"], s["trigger_config"], s["action_type"], s["action_config"]),
        )
    return redirect(request, "/automations")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
