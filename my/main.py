"""
MY PLANNER - Universal personal planner with profile isolation & shared folders
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
    UploadFile, File, WebSocket, WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

import uvicorn

# ── Common modules ──
from common.utils import fix_mojibake, clamp_priority, validate_date_str, validate_datetime_str, clamp_text, safe_int
from common.filters import register_filters, render_error_page
from common.middleware import EventBus, CSRFMiddleware, SyncBroadcastMiddleware, patch_formparser_utf8
from common.constants import PRIORITY_MAP, REPEAT_MAP, WEEKDAY_NAMES
from common.recurrence import next_occurrence, expand_recurring_events
from common.stats import get_stats, get_weekly_chart_data, week_number_in_month, get_week_range, get_productivity_insights
from common.routers.timetable import resolve_timetable_blocks as _resolve_timetable_blocks
from common.achievements import (
    check_achievements, get_earned_achievements, get_completion_streak,
    get_today_completed_count, get_total_completed, ACHIEVEMENT_DEFS,
)
from common.webpush import get_vapid_public_key, save_subscription, remove_subscription, send_push
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

app = FastAPI(title="MY PLANNER", docs_url=None, redoc_url=None, lifespan=lifespan)


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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # CSP: 'unsafe-inline' still required — 3 inline <script> blocks remain in base.html
        # (theme detect, accent/font restore, _partialRefresh) + Jinja-dependent scripts.
        # 5 blocks extracted to static/js/ (sidebar-favorites, slash-commands, htmx-helpers, actions).
        response.headers["Content-Security-Policy"] = (
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' wss: ws:; "
            "frame-ancestors 'none'"
        )
        return response


class StaticCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app.add_middleware(ProfileCheckMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SyncBroadcastMiddleware, event_bus=event_bus,
                   skip_paths=("/worklogs/upload-image",),
                   skip_prefixes=("/files/",))
app.add_middleware(StaticCacheMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)
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
    # Detect HTMX partial request
    ctx["is_htmx"] = "HX-Request" in request.headers
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
    ctx.setdefault("config", {"planner_name": "MY PLANNER"})
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


# ── WebSocket endpoint ──

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    sid, queue = event_bus.subscribe()
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30)
                if isinstance(msg, dict):
                    await websocket.send_json(msg)
                else:
                    await websocket.send_json({"event": "sync", "data": msg})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        event_bus.unsubscribe(sid)


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


# ── Content-hash cache busting ──
_asset_hash_cache: dict[str, str] = {}


def asset_hash(rel_path: str) -> str:
    """Return md5 hash prefix for a static asset (cached per process)."""
    if rel_path in _asset_hash_cache:
        return _asset_hash_cache[rel_path]
    full = BASE_DIR / "static" / rel_path
    try:
        h = hashlib.md5(full.read_bytes()).hexdigest()[:8]
    except FileNotFoundError:
        h = "0"
    _asset_hash_cache[rel_path] = h
    return h


templates.env.globals["asset_hash"] = asset_hash


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

        # notification_settings + timetable_blocks tables
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notification_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                target_type TEXT NOT NULL,
                offsets TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER DEFAULT 1,
                UNIQUE(profile_id, target_type)
            );

            CREATE TABLE IF NOT EXISTS timetable_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                day_type TEXT NOT NULL DEFAULT 'default',
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                title TEXT NOT NULL,
                color TEXT DEFAULT '#6366f1',
                icon TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_timetable_blocks_profile ON timetable_blocks(profile_id, day_type);

        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            achieved_at TEXT NOT NULL DEFAULT (date('now', 'localtime')),
            UNIQUE(profile_id, achievement_id)
        );
        CREATE INDEX IF NOT EXISTS idx_achievements_profile ON achievements(profile_id);

        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL DEFAULT '',
            subscription_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(profile_id, endpoint)
        );
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
        (profile_id, "MY PLANNER 둘러보기", 1, today.isoformat(), '["시작"]', 1),
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
        (profile_id, "MY PLANNER 시작!", f"{today.isoformat()}T09:00", "#d97706", "환영합니다! 이 일정을 수정하거나 삭제해보세요."),
    )
    conn.execute(
        "INSERT INTO memos (profile_id, author, title, content) VALUES (?,?,?,?)",
        (profile_id, "MY PLANNER", "환영합니다!", "## 시작 가이드\n\n- **할 일**: 좌측 메뉴에서 할 일을 관리하세요\n- **캘린더**: 일정을 한눈에 확인하세요\n- **집중 모드**: 포모도로 타이머로 생산성을 높이세요\n- **양식**: 13종의 업무 양식을 바로 사용하세요"),
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
from common.routers import memos as _r_memos
from common.routers import worklogs as _r_worklogs, events as _r_events
from common.routers import todos as _r_todos
from common.routers import settings as _r_settings, misc as _r_misc
from common.routers import sse as _r_sse
from common.routers import auth as _r_auth
from common.routers import notifications as _r_notifications
from common.routers import achievements as _r_achievements
from common.routers import push as _r_push
from common.routers import export_import as _r_export_import
from common.routers import gcal as _r_gcal
from common.routers import habits as _r_habits
from common.routers import engagement as _r_engagement
from common.routers import timetable as _r_timetable
from common.routers import today as _r_today
from common.routers import stats as _r_stats
from common.routers import categories as _r_categories
from common.routers import ddays as _r_ddays
from common.routers import links as _r_links

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
app.state.app_display_name = "MY PLANNER"
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
app.include_router(_r_worklogs.router)
app.include_router(_r_events.router)
app.include_router(_r_todos.router)
app.include_router(_r_settings.router)
app.include_router(_r_misc.router)
app.include_router(_r_sse.router)
app.include_router(_r_auth.router)
app.include_router(_r_notifications.router)
app.include_router(_r_achievements.router)
app.include_router(_r_push.router)
app.include_router(_r_export_import.router)
app.include_router(_r_gcal.router)
app.include_router(_r_habits.router)
app.include_router(_r_engagement.router)
app.include_router(_r_timetable.router)
app.include_router(_r_today.router)
app.include_router(_r_stats.router)
app.include_router(_r_categories.router)
app.include_router(_r_ddays.router)
app.include_router(_r_links.router)


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

app.state.gcal_refresh_token = _gcal_refresh_token
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
            # Batch subtask counts
            _plan_ids = [t["id"] for t in plan_todos]
            _sub_counts: dict = {}
            if _plan_ids:
                _ph = ",".join("?" * len(_plan_ids))
                for _r in conn.execute(f"SELECT todo_id, COUNT(*) as cnt FROM subtasks WHERE todo_id IN ({_ph}) GROUP BY todo_id", _plan_ids).fetchall():
                    _sub_counts[_r["todo_id"]] = _r["cnt"]
            week_days = []
            no_due_todos = [dict(t) for t in plan_todos if not t["due_date"]] if _include_no_due else []
            for i in range(7):
                d = monday + timedelta(days=i)
                day_todos = []
                for t in plan_todos:
                    if t["due_date"] == d.isoformat():
                        td = dict(t)
                        td["subtask_count"] = _sub_counts.get(td["id"], 0)
                        day_todos.append(td)
                # Attach no-due-date todos to today's column
                if _include_no_due and d == today:
                    for t in no_due_todos:
                        t["subtask_count"] = _sub_counts.get(t["id"], 0)
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

        # Timetable widget data
        tt_blocks = _resolve_timetable_blocks(conn, pid, today)
        now = datetime.now()
        now_minutes = now.hour * 60 + now.minute
        tt_widget_blocks = []; tt_current = None; tt_next = None
        for ub in tt_blocks:
            try:
                sp = ub["start_time"].split(":"); ep = ub["end_time"].split(":")
                s_min = int(sp[0])*60+int(sp[1]); e_min = int(ep[0])*60+int(ep[1])
                start_h = int(sp[0])+int(sp[1])/60.0; end_h = int(ep[0])+int(ep[1])/60.0
            except Exception: continue
            if end_h <= start_h: end_h = 24.0; e_min = 1440
            bdata = {"title":f"{ub.get('icon','')} {ub['title']}".strip(),"start_time":ub["start_time"],"end_time":ub["end_time"],"start_hour":start_h,"end_hour":end_h,"color":ub.get("color","#6366f1")}
            tt_widget_blocks.append(bdata)
            if s_min <= now_minutes < e_min: tt_current = bdata
            elif s_min > now_minutes and tt_next is None: tt_next = bdata

        # Achievement & gamification data
        try:
            streak = get_completion_streak(conn, pid)
            today_done_count = get_today_completed_count(conn, pid)
            today_total_count = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE profile_id=? AND ((due_date <= ? AND completed=0) OR (completed=1 AND date(completed_at)=?))",
                (pid, today_str, today_str),
            ).fetchone()[0] or 0
            check_achievements(conn, pid)
            earned_count = conn.execute(
                "SELECT COUNT(*) FROM achievements WHERE profile_id=?", (pid,)
            ).fetchone()[0] or 0
        except Exception:
            streak = 0; today_done_count = 0; today_total_count = 1; earned_count = 0

        insights = get_productivity_insights(conn, pid)

    return render(request, "dashboard.html", {
        "page": "dashboard",
        "stats": stats,
        "today_todos": [dict(r) for r in today_todos],
        "week_events": [dict(r) for r in week_events],
        "recent_memos": [dict(r) for r in recent_memos],
        "categories": [dict(r) for r in categories],
        "project_progress": [dict(r) for r in project_progress],
        "today_worklogs": [dict(r) for r in today_worklogs],
        "today_work_hours": round(today_worklogs_hours, 1),
        "time_budgets": time_budgets,
        "over_budget": over_budget,
        "priority_map": PRIORITY_MAP,
        "plan_view": plan_view,
        "plan_offset": plan_offset,
        "tt_widget_blocks": tt_widget_blocks,
        "tt_current": tt_current,
        "tt_next": tt_next,
        "streak": streak,
        "today_done_count": today_done_count,
        "today_total_count": today_total_count if today_total_count > 0 else max(today_done_count, 1),
        "earned_count": earned_count,
        "total_achievements": len(ACHIEVEMENT_DEFS),
        "insights": insights,
        **plan_data,
    })


# ── Achievements, Push, Quick-add, Import/Export — moved to common/routers/ ──


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


# ── Google Calendar OAuth — moved to common/routers/gcal.py ──


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


# ── D-days, Links, Stats, QR, Habits, Onboarding, Morning Brief, PWA,
#    Timetable, Today, Automations starter — moved to common/routers/ ──


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
