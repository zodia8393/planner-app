"""
Work Planner - Professional task & schedule management
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
import hashlib
import secrets
import shutil
import zipfile
import io as io_mod
from datetime import datetime, date as date_mod, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Form, Query, HTTPException, Response, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

import uvicorn

from common.utils import fix_mojibake, clamp_priority, validate_date_str, validate_datetime_str, clamp_text
from common.middleware import EventBus, CSRFMiddleware, SyncBroadcastMiddleware
from common.filters import register_filters, render_error_page
from common.db import get_db as _get_db_common
from common.image import MAGIC_BYTES, _check_image_magic
from common.excel import parse_excel_with_merges, infer_field_type
from common.holidays import KOREAN_HOLIDAYS, get_holidays_for_month
from common.middleware import patch_formparser_utf8
from common.constants import PRIORITY_MAP, REPEAT_MAP, WEEKDAY_NAMES, ROLE_COLORS
from common.recurrence import next_occurrence, expand_recurring_events
from common.stats import get_stats, get_weekly_chart_data, week_number_in_month, get_week_range

# ── Starlette FormParser latin-1 -> utf-8 patch ──
patch_formparser_utf8()


# ── SSE EventBus ──
event_bus = EventBus()


def hash_pin(pin: str, salt: str = "") -> str:
    if salt:
        return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex() + ":" + salt
    salt = secrets.token_hex(16)
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex() + ":" + salt


def verify_pin(pin: str, stored: str) -> bool:
    if ":" in stored:
        _, salt = stored.rsplit(":", 1)
        return hash_pin(pin, salt) == stored
    return hashlib.sha256(pin.encode()).hexdigest() == stored


# ── Cookie / session constants ──
SESSION_COOKIE = "work_session"
SESSION_TOKENS: dict[str, int] = {}  # token -> profile_id
PROFILE_COOKIE = "work_profile"


# ── Network group helpers ──
def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def _ip_to_network_group(ip: str) -> str:
    parts = ip.split(".")
    if len(parts) >= 3:
        return ".".join(parts[:3])
    if ":" in ip:
        segments = ip.split(":")
        return ":".join(segments[:3]) if len(segments) >= 3 else ip
    return ip


def get_network_group(request: Request) -> str:
    return _ip_to_network_group(get_client_ip(request))


# ── Middleware ──
PUBLIC_PATHS = {"/login", "/health", "/static", "/uploads", "/favicon.ico", "/sse", "/select-profile", "/profiles", "/auth", "/cal", "/worklog-images", "/backgrounds"}


class PinAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in PUBLIC_PATHS):
            return await call_next(request)
        profile_id = request.cookies.get(PROFILE_COOKIE)
        if not profile_id:
            return await call_next(request)
        try:
            with get_db() as conn:
                profile = conn.execute("SELECT pin FROM work_profiles WHERE id=?", (int(profile_id),)).fetchone()
        except (sqlite3.OperationalError, ValueError):
            return await call_next(request)
        if not profile or not profile["pin"]:
            return await call_next(request)
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            tid = SESSION_TOKENS.get(token)
            if tid == int(profile_id):
                return await call_next(request)
        if path.startswith("/api/") or request.headers.get("HX-Request"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=303)


class ProfileSelectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in PUBLIC_PATHS):
            return await call_next(request)
        if not request.cookies.get(PROFILE_COOKIE):
            if request.headers.get("HX-Request"):
                return HTMLResponse("", headers={"HX-Redirect": "/select-profile"})
            if path.startswith("/api/"):
                return JSONResponse({"error": "no profile"}, status_code=401)
            return RedirectResponse("/select-profile", status_code=303)
        return await call_next(request)


# ── Path setup ──
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "work.db"
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
BACKGROUNDS_DIR = BASE_DIR / "static" / "backgrounds"
(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)


# ── FastAPI app ──
@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

app = FastAPI(title="Work Planner", docs_url=None, redoc_url=None, lifespan=lifespan)

app.add_middleware(PinAuthMiddleware)
app.add_middleware(ProfileSelectMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SyncBroadcastMiddleware, event_bus=event_bus, skip_paths=("/worklogs/upload-image",))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
WORKLOG_IMG_DIR = BASE_DIR / "data" / "worklog_images"
WORKLOG_IMG_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/worklog-images", StaticFiles(directory=str(WORKLOG_IMG_DIR)), name="worklog_images")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_bg_setting(profile_id: int) -> dict:
    """Get background setting for a profile."""
    default = {"type": "none", "preset": "", "image": "", "opacity": 0.7}
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT value FROM user_settings WHERE profile_id=? AND key='background'",
                (str(profile_id),),
            ).fetchone()
            if row and row["value"]:
                return json.loads(row["value"])
    except (sqlite3.OperationalError, json.JSONDecodeError):
        pass
    return default


def render(request: Request, name: str, context: dict = None):
    ctx = context or {}
    ap = request.cookies.get(PROFILE_COOKIE)
    if ap:
        try:
            ap_id = int(ap)
            with get_db() as conn:
                ap_row = conn.execute("SELECT * FROM work_profiles WHERE id=?", (ap_id,)).fetchone()
                if ap_row:
                    ctx["active_profile"] = dict(ap_row)
                    ctx["active_profile_id"] = ap_id
        except (ValueError, TypeError):
            pass
    if "active_profile" not in ctx:
        ctx["active_profile"] = None
        ctx["active_profile_id"] = None
    if ctx.get("active_profile"):
        ctx["needs_pin_setup"] = not ctx["active_profile"].get("pin")
    else:
        ctx["needs_pin_setup"] = False
    ctx.setdefault("today", date_mod.today())
    # Background setting
    pid = ctx.get("active_profile_id") or 0
    if "bg_setting" not in ctx:
        ctx["bg_setting"] = get_bg_setting(pid)
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


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return HTMLResponse(render_error_page(500, "서버 오류가 발생했습니다"), status_code=500)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        if exc.status_code == 404:
            return HTMLResponse(render_error_page(404, "페이지를 찾을 수 없습니다"), status_code=404)
        raise exc
    import traceback; traceback.print_exc()
    return HTMLResponse(render_error_page(500, "서버 오류가 발생했습니다"), status_code=500)

register_filters(templates)


# ── DB management ──
def get_db():
    return _get_db_common(DB_PATH)


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS work_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT DEFAULT '',
            emoji TEXT DEFAULT '💼',
            pin TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            pin_hash TEXT DEFAULT '',
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        INSERT OR IGNORE INTO app_settings (id) VALUES (1);

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL UNIQUE,
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
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS file_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            uploader TEXT NOT NULL DEFAULT '',
            uploaded_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

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

        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            network_group TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            priority INTEGER DEFAULT 0,
            pinned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_date);
        CREATE INDEX IF NOT EXISTS idx_todos_completed ON todos(completed);
        CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);
        CREATE INDEX IF NOT EXISTS idx_file_uploads_path ON file_uploads(file_path);
        CREATE INDEX IF NOT EXISTS idx_worklogs_profile ON work_logs(profile_id);
        CREATE INDEX IF NOT EXISTS idx_worklogs_date ON work_logs(log_date);
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
            profile_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (profile_id, key)
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

        CREATE TABLE IF NOT EXISTS ical_tokens (
            profile_id INTEGER PRIMARY KEY,
            token TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
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
        """)

        for tbl in ("work_profiles", ):
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN role TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
        for tbl in ("todos", "events", "memos"):
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN profile_id INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

        # Memos: add title and category_id columns
        for col, sql in [
            ("title", "ALTER TABLE memos ADD COLUMN title TEXT DEFAULT ''"),
            ("category_id", "ALTER TABLE memos ADD COLUMN category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL"),
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass

        # Migration: add emoji/color to form_templates
        ft_cols = [r[1] for r in conn.execute("PRAGMA table_info(form_templates)").fetchall()]
        if "emoji" not in ft_cols:
            conn.execute("ALTER TABLE form_templates ADD COLUMN emoji TEXT DEFAULT '📝'")
        if "color" not in ft_cols:
            conn.execute("ALTER TABLE form_templates ADD COLUMN color TEXT DEFAULT '#6366f1'")

        # Migration: add recurrence columns to todos and events
        todo_cols = [r[1] for r in conn.execute("PRAGMA table_info(todos)").fetchall()]
        if "recurrence_end" not in todo_cols:
            conn.execute("ALTER TABLE todos ADD COLUMN recurrence_end TEXT DEFAULT ''")
        ev_cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
        if "recurrence" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN recurrence TEXT DEFAULT ''")
        if "recurrence_end" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN recurrence_end TEXT DEFAULT ''")
        if "gcal_event_id" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN gcal_event_id TEXT DEFAULT ''")

        # Migration: add energy_level column to todos (1=Low, 2=Medium, 3=High)
        if "energy_level" not in todo_cols:
            conn.execute("ALTER TABLE todos ADD COLUMN energy_level INTEGER DEFAULT 2")

        existing = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if existing == 0:
            conn.executemany(
                "INSERT INTO categories (name, color, sort_order) VALUES (?, ?, ?)",
                [("업무", "#6366f1", 0), ("회의", "#8b5cf6", 1), ("개인", "#10b981", 2), ("기타", "#f59e0b", 3)],
            )

        existing_profiles = conn.execute("SELECT COUNT(*) FROM work_profiles").fetchone()[0]
        if existing_profiles == 0:
            conn.executemany(
                "INSERT INTO work_profiles (name, emoji, role) VALUES (?, ?, ?)",
                [
                    ("조형준", "🦁", "주임"),
                    ("김동환", "🐺", "대리"),
                    ("최정우", "🦅", "차장"),
                    ("김태호", "🐻", "차장"),
                    ("박준태", "🐯", "부장"),
                ],
            )

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


# ── Audit log helper ──
def _audit_log(conn, entity_type: str, entity_id: int, action: str, changes: dict = None, profile_id: str = None):
    """Insert a lightweight audit record."""
    conn.execute(
        "INSERT INTO audit_log (entity_type, entity_id, action, changes_json, profile_id) VALUES (?,?,?,?,?)",
        (entity_type, entity_id, action, json.dumps(changes or {}, ensure_ascii=False), profile_id),
    )


# ── Utility functions ──


# ── Google Calendar OAuth2 ──
GCAL_CLIENT_ID = os.environ.get("GCAL_CLIENT_ID", "")
GCAL_CLIENT_SECRET = os.environ.get("GCAL_CLIENT_SECRET", "")
GCAL_SCOPES = "https://www.googleapis.com/auth/calendar.readonly"
GCAL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GCAL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GCAL_API_BASE = "https://www.googleapis.com/calendar/v3"


def _gcal_redirect_uri(request: Request) -> str:
    host = request.headers.get("host", "localhost:8001")
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{host}/settings/gcal/callback"


async def _gcal_refresh_token(profile_id: int) -> Optional[str]:
    """Refresh access token if expired, return valid access_token or None."""
    import httpx
    with get_db() as conn:
        row = conn.execute("SELECT * FROM gcal_tokens WHERE profile_id=?", (profile_id,)).fetchone()
    if not row:
        return None
    expiry = datetime.fromisoformat(row["token_expiry"])
    if datetime.now() < expiry - timedelta(minutes=2):
        return row["access_token"]
    async with httpx.AsyncClient() as client:
        resp = await client.post(GCAL_TOKEN_URL, data={
            "client_id": GCAL_CLIENT_ID,
            "client_secret": GCAL_CLIENT_SECRET,
            "refresh_token": row["refresh_token"],
            "grant_type": "refresh_token",
        })
    if resp.status_code != 200:
        return None
    data = resp.json()
    new_expiry = (datetime.now() + timedelta(seconds=data["expires_in"])).isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE gcal_tokens SET access_token=?, token_expiry=? WHERE profile_id=?",
            (data["access_token"], new_expiry, profile_id),
        )
    return data["access_token"]


async def _gcal_fetch_events(profile_id: int, time_min: str, time_max: str) -> list:
    """Fetch events from Google Calendar API for given date range."""
    import httpx
    token = await _gcal_refresh_token(profile_id)
    if not token:
        return []
    with get_db() as conn:
        row = conn.execute("SELECT calendar_id FROM gcal_tokens WHERE profile_id=?", (profile_id,)).fetchone()
    cal_id = row["calendar_id"] if row else "primary"
    params = {
        "timeMin": f"{time_min}T00:00:00+09:00",
        "timeMax": f"{time_max}T23:59:59+09:00",
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "200",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GCAL_API_BASE}/calendars/{cal_id}/events",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        return []
    items = resp.json().get("items", [])
    events = []
    for item in items:
        start = item.get("start", {})
        end = item.get("end", {})
        start_dt = start.get("dateTime", start.get("date", ""))
        end_dt = end.get("dateTime", end.get("date", ""))
        events.append({
            "id": f"gcal_{item['id'][:8]}",
            "title": item.get("summary", "(제목 없음)"),
            "start_time": start_dt,
            "end_time": end_dt,
            "color": "#4285f4",
            "is_gcal": True,
            "location": item.get("location", ""),
        })
    return events


def calc_dday(target_date_str: str) -> int:
    try:
        target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        return (target - date_mod.today()).days
    except (ValueError, TypeError):
        return 0


def get_profile_id(request: Request) -> int:
    try:
        return int(request.cookies.get(PROFILE_COOKIE, "0"))
    except (ValueError, TypeError):
        return 0


def get_profile_name(request: Request) -> str:
    ap = request.cookies.get(PROFILE_COOKIE)
    if ap:
        try:
            with get_db() as conn:
                row = conn.execute("SELECT name FROM work_profiles WHERE id=?", (int(ap),)).fetchone()
                if row:
                    return row["name"]
        except (ValueError, TypeError):
            pass
    return ""


def redirect(request: Request, url: str):
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def _get_return_url(request: Request, default: str) -> str:
    ret = request.query_params.get("return_url", "")
    if ret and ret.startswith("/"):
        return ret
    referer = request.headers.get("referer", "")
    if referer:
        path = urlparse(referer).path
        query = urlparse(referer).query
        if path in ("/", "/calendar"):
            return f"{path}?{query}" if query else path
    return default



# ── Include common routers ──
from common.routers import memos as _r_memos, notices as _r_notices
from common.routers import worklogs as _r_worklogs, events as _r_events
from common.routers import todos as _r_todos, forms as _r_forms
from common.routers import settings as _r_settings, misc as _r_misc

app.state.get_db = get_db
app.state.get_profile_id = get_profile_id
app.state.get_profile_name = get_profile_name
app.state.render = render
app.state.redirect = redirect
app.state.templates = templates
app.state.audit_log = _audit_log
app.state.event_bus = event_bus
app.state.base_dir = BASE_DIR
app.state.app_name = "work-planner"
app.state.worklog_img_dir = WORKLOG_IMG_DIR
app.state.get_categories = lambda conn, pid: conn.execute(
    "SELECT * FROM categories ORDER BY sort_order").fetchall()
app.state.get_network_group = get_network_group

app.include_router(_r_memos.router)
app.include_router(_r_notices.router)
app.include_router(_r_worklogs.router)
app.include_router(_r_events.router)
app.include_router(_r_todos.router)
app.include_router(_r_forms.router)
app.include_router(_r_settings.router)
app.include_router(_r_misc.router)



# ── Routes: Profile Selection & Auth ──
@app.get("/select-profile", response_class=HTMLResponse)
async def select_profile_page(request: Request):
    with get_db() as conn:
        profiles = conn.execute("SELECT * FROM work_profiles ORDER BY id").fetchall()
    return render(request, "select_profile.html", {
        "page": "select_profile",
        "profiles": [dict(p) for p in profiles],
        "role_colors": ROLE_COLORS,
    })


@app.post("/select-profile", response_class=HTMLResponse)
async def select_profile(request: Request, profile_id: int = Form(...)):
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(PROFILE_COOKIE, str(profile_id), max_age=86400 * 365, httponly=True, secure=request.url.scheme == "https", samesite="lax")
    return resp


@app.post("/profiles", response_class=HTMLResponse)
async def create_profile(request: Request,
                         name: str = Form(...),
                         emoji: str = Form("💼")):
    name = clamp_text(fix_mojibake(name), 50)
    emoji = fix_mojibake(emoji) or "💼"
    with get_db() as conn:
        conn.execute("INSERT INTO work_profiles (name, emoji) VALUES (?, ?)", (name, emoji))
    return RedirectResponse("/select-profile", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    pid = get_profile_id(request)
    profile_name = ""
    profile_emoji = ""
    if pid:
        with get_db() as conn:
            row = conn.execute("SELECT name, emoji FROM work_profiles WHERE id=?", (pid,)).fetchone()
            if row:
                profile_name = row["name"]
                profile_emoji = row["emoji"]
    return render(request, "login.html", {"page": "login", "profile_name": profile_name, "profile_emoji": profile_emoji})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, pin: str = Form(...)):
    pid = get_profile_id(request)
    with get_db() as conn:
        profile = conn.execute("SELECT pin FROM work_profiles WHERE id=?", (pid,)).fetchone()
    if not profile or not profile["pin"]:
        return RedirectResponse("/", status_code=303)
    if not verify_pin(pin, profile["pin"]):
        return render(request, "login.html", {"page": "login", "error": "PIN이 올바르지 않습니다"})
    token = secrets.token_urlsafe(32)
    SESSION_TOKENS[token] = pid
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, max_age=86400 * 30, httponly=True, secure=request.url.scheme == "https", samesite="lax")
    return resp


@app.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        SESSION_TOKENS.pop(token, None)
    resp = RedirectResponse("/select-profile", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    resp.delete_cookie(PROFILE_COOKIE)
    return resp


@app.get("/auth/setup-pin", response_class=HTMLResponse)
async def setup_pin_page(request: Request):
    return render(request, "setup_pin.html", {"page": "setup_pin"})


@app.post("/auth/setup-pin")
async def setup_pin(request: Request, pin: str = Form(...), pin_confirm: str = Form("")):
    pid = get_profile_id(request)
    if pin != pin_confirm:
        return render(request, "setup_pin.html", {"page": "setup_pin", "error": "PIN이 일치하지 않습니다"})
    if len(pin) < 4:
        return render(request, "setup_pin.html", {"page": "setup_pin", "error": "PIN은 최소 4자리입니다"})
    with get_db() as conn:
        conn.execute("UPDATE work_profiles SET pin=? WHERE id=?", (hash_pin(pin), pid))
    token = secrets.token_urlsafe(32)
    SESSION_TOKENS[token] = pid
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, max_age=86400 * 30, httponly=True, secure=request.url.scheme == "https", samesite="lax")
    return resp


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


# ── Routes: Dashboard ──
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, plan_view: str = "week", plan_offset: int = 0):
    pid = get_profile_id(request)
    today = date_mod.today()
    today_str = today.isoformat()

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
            WHERE m.profile_id = ?
            ORDER BY m.created_at DESC LIMIT 3
        """, (pid,)).fetchall()

        categories = conn.execute("SELECT * FROM categories ORDER BY sort_order").fetchall()

        project_progress = conn.execute("""
            SELECT c.name, c.color,
                   COUNT(CASE WHEN t.completed=0 THEN 1 END) as pending,
                   COUNT(CASE WHEN t.completed=1 THEN 1 END) as done,
                   COUNT(*) as total
            FROM categories c
            LEFT JOIN todos t ON t.category_id = c.id AND t.profile_id = ?
            GROUP BY c.id HAVING total > 0
            ORDER BY c.sort_order
        """, (pid,)).fetchall()

        # Today's work logs
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

        # Recent notices
        network_group = get_network_group(request)
        recent_notices = conn.execute("""
            SELECT n.*, p.name as author_name
            FROM notices n LEFT JOIN work_profiles p ON n.profile_id = p.id
            WHERE n.network_group = ? OR n.network_group = ''
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
            plan_todos = conn.execute("""
                SELECT t.*, c.name as category_name, c.color as category_color
                FROM todos t LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.due_date BETWEEN ? AND ? AND t.profile_id = ?
                ORDER BY t.due_date ASC, t.priority ASC, t.sort_order ASC
            """, (monday.isoformat(), sunday.isoformat(), pid)).fetchall()
            week_days = []
            for i in range(7):
                d = monday + timedelta(days=i)
                day_todos = [dict(t) for t in plan_todos if t["due_date"] == d.isoformat()]
                week_days.append({
                    "date": d, "date_str": d.isoformat(),
                    "label": f"{WEEKDAY_NAMES[i]} {d.strftime('%m/%d')}",
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

        year_ago = (date_mod.today() - timedelta(days=364)).isoformat()
        heatmap_data = conn.execute(
            "SELECT date(completed_at) as d, COUNT(*) as cnt FROM todos "
            "WHERE profile_id=? AND completed=1 AND completed_at>=? "
            "GROUP BY date(completed_at) ORDER BY d",
            (pid, year_ago)
        ).fetchall()
        heatmap = {row["d"]: row["cnt"] for row in heatmap_data if row["d"]}

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
        "heatmap": heatmap,
        "heatmap_start": year_ago,
        "heatmap_today": date_mod.today().isoformat(),
        **plan_data,
    })


# ── Routes: Todos ──
















# ── Subtasks ──






# ── Routes: Todo Templates ──










# ── Routes: Automation Rules ──








# ── Routes: Calendar ──










# ── Routes: Memos (with HTMX partial swap) ──












# ── Routes: Settings ──


@app.post("/settings/profile", response_class=HTMLResponse)
async def settings_update_profile(request: Request, name: str = Form(...)):
    pid = get_profile_id(request)
    name = clamp_text(fix_mojibake(name), 50).strip()
    if not name:
        name = "사용자"
    with get_db() as conn:
        conn.execute("UPDATE work_profiles SET name=? WHERE id=?", (name, pid))
    return redirect(request, "/settings")










# ── Background settings ──
@app.post("/settings/background")
async def settings_background(request: Request):
    pid = get_profile_id(request)
    form = await request.form()
    bg_type = str(form.get("type", "none"))
    preset = str(form.get("preset", ""))
    opacity = float(form.get("opacity", 0.7))
    opacity = max(0.3, min(0.95, opacity))

    bg_data = {"type": bg_type, "preset": preset, "image": "", "opacity": opacity}

    if bg_type == "upload":
        file = form.get("file")
        if file and hasattr(file, "filename") and file.filename:
            # Validate file
            ext = Path(file.filename).suffix.lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                return redirect(request, "/settings")
            content = await file.read()
            if len(content) > 5 * 1024 * 1024:  # 5MB max
                return redirect(request, "/settings")
            # Save file
            fname = f"{pid}_{uuid.uuid4().hex[:8]}{ext}"
            fpath = BACKGROUNDS_DIR / fname
            fpath.write_bytes(content)
            bg_data["image"] = f"/static/backgrounds/{fname}"
        else:
            # Keep existing image if no new file uploaded
            existing = get_bg_setting(pid)
            if existing.get("image"):
                bg_data["image"] = existing["image"]

    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (profile_id, key, value) VALUES (?, 'background', ?)",
            (str(pid), json.dumps(bg_data)),
        )
    return redirect(request, "/settings")


@app.get("/api/settings/background")
async def api_get_background(request: Request):
    pid = get_profile_id(request)
    return JSONResponse(get_bg_setting(pid))


# ── Routes: Backup & Restore ──




# ── Google Calendar OAuth2 Routes ──
@app.get("/settings/gcal/connect")
async def gcal_connect(request: Request):
    if not GCAL_CLIENT_ID:
        raise HTTPException(400, "GCAL_CLIENT_ID 환경변수가 설정되지 않았습니다")
    from urllib.parse import urlencode
    params = urlencode({
        "client_id": GCAL_CLIENT_ID,
        "redirect_uri": _gcal_redirect_uri(request),
        "response_type": "code",
        "scope": GCAL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": str(get_profile_id(request)),
    })
    return RedirectResponse(f"{GCAL_AUTH_URL}?{params}")


@app.get("/settings/gcal/callback")
async def gcal_callback(request: Request, code: str = "", error: str = "", state: str = ""):
    if error or not code:
        return redirect(request, "/settings")
    import httpx
    pid = int(state) if state.isdigit() else get_profile_id(request)
    async with httpx.AsyncClient() as client:
        resp = await client.post(GCAL_TOKEN_URL, data={
            "code": code,
            "client_id": GCAL_CLIENT_ID,
            "client_secret": GCAL_CLIENT_SECRET,
            "redirect_uri": _gcal_redirect_uri(request),
            "grant_type": "authorization_code",
        })
    if resp.status_code != 200:
        raise HTTPException(400, f"Google 토큰 교환 실패: {resp.text[:200]}")
    data = resp.json()
    expiry = (datetime.now() + timedelta(seconds=data["expires_in"])).isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO gcal_tokens (profile_id, access_token, refresh_token, token_expiry)
            VALUES (?, ?, ?, ?)
        """, (pid, data["access_token"], data.get("refresh_token", ""), expiry))
    return redirect(request, "/settings")


@app.post("/settings/gcal/disconnect")
async def gcal_disconnect(request: Request):
    pid = get_profile_id(request)
    with get_db() as conn:
        conn.execute("DELETE FROM gcal_tokens WHERE profile_id=?", (pid,))
    return redirect(request, "/settings")


@app.post("/settings/gcal/calendar-id")
async def gcal_set_calendar_id(request: Request, calendar_id: str = Form("primary")):
    pid = get_profile_id(request)
    with get_db() as conn:
        conn.execute("UPDATE gcal_tokens SET calendar_id=? WHERE profile_id=?", (calendar_id, pid))
    return redirect(request, "/settings")


@app.get("/api/gcal/calendars")
async def gcal_list_calendars(request: Request):
    import httpx
    pid = get_profile_id(request)
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












# ── Focus mode ──


# ── Routes: Plans ──
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


@app.post("/api/ical-token")
async def generate_ical_token(request: Request):
    """Generate (or regenerate) a per-profile iCal subscription token."""
    pid = get_profile_id(request)
    token = secrets.token_urlsafe(32)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO ical_tokens (profile_id, token) VALUES (?, ?) "
            "ON CONFLICT(profile_id) DO UPDATE SET token=excluded.token, "
            "created_at=datetime('now','localtime')",
            (pid, token),
        )
    return {"token": token}


@app.get("/api/ical-token")
async def get_ical_token(request: Request):
    """Return existing iCal token for current profile, or empty string."""
    pid = get_profile_id(request)
    with get_db() as conn:
        row = conn.execute("SELECT token FROM ical_tokens WHERE profile_id=?", (pid,)).fetchone()
    return {"token": row["token"] if row else ""}


# ── Routes: Audit Log ──


# ── Global Search ──




# ── Quick-add from dashboard ──


# ── Routes: Shared Files (/공유폴더) ──
SHARED_ROOT = Path("/공유폴더")

FILE_ICONS = {
    ".pdf": "📄", ".hwp": "📝", ".hwpx": "📝",
    ".doc": "📘", ".docx": "📘", ".ppt": "📙", ".pptx": "📙",
    ".xls": "📗", ".xlsx": "📗", ".csv": "📊",
    ".zip": "📦", ".tar": "📦", ".gz": "📦", ".7z": "📦", ".rar": "📦",
    ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️", ".gif": "🖼️", ".bmp": "🖼️", ".svg": "🖼️",
    ".mp4": "🎬", ".avi": "🎬", ".mkv": "🎬", ".mov": "🎬",
    ".py": "🐍", ".r": "📐", ".sql": "🗃️", ".json": "📋", ".xml": "📋",
    ".txt": "📃", ".md": "📃", ".log": "📃",
}

PREVIEW_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp",
    ".pdf",
    ".txt", ".md", ".log", ".csv", ".json", ".xml", ".py", ".r", ".sql", ".html", ".css", ".js",
}


def safe_path(subpath: str) -> Path:
    resolved = (SHARED_ROOT / subpath).resolve()
    if not str(resolved).startswith(str(SHARED_ROOT.resolve())):
        raise HTTPException(403, "접근 금지")
    return resolved


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} TB"


@app.get("/files", response_class=HTMLResponse)
@app.get("/files/{path:path}", response_class=HTMLResponse)
async def files_page(request: Request, path: str = ""):
    target = safe_path(path)
    if not target.exists():
        raise HTTPException(404, "경로를 찾을 수 없습니다")

    if target.is_file():
        import mimetypes
        from urllib.parse import quote
        mime, _ = mimetypes.guess_type(target.name)
        encoded_name = quote(target.name)
        file_size = target.stat().st_size

        preview = request.query_params.get("preview")
        if preview:
            headers = {"Content-Length": str(file_size)}
            if mime and mime.startswith(("image/", "application/pdf")):
                headers["Content-Disposition"] = "inline"
            else:
                headers["Content-Disposition"] = "inline"
                if not mime or not mime.startswith("text/"):
                    mime = "text/plain; charset=utf-8"
            return StreamingResponse(open(target, "rb"), media_type=mime or "text/plain", headers=headers)

        return StreamingResponse(
            open(target, "rb"),
            media_type=mime or "application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
                "Content-Length": str(file_size),
            },
        )

    with get_db() as conn:
        upload_rows = conn.execute("SELECT file_path, uploader, uploaded_at FROM file_uploads").fetchall()
    upload_map = {r["file_path"]: {"uploader": r["uploader"], "uploaded_at": r["uploaded_at"]} for r in upload_rows}

    items = []
    for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        try:
            stat = entry.stat()
        except OSError:
            continue
        ext = entry.suffix.lower()
        rel = f"{path}/{entry.name}".lstrip("/")
        meta = upload_map.get(rel, {})
        is_image = ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp"}
        is_pdf = ext == ".pdf"
        is_text = ext in {".txt", ".md", ".log", ".csv", ".json", ".xml", ".py", ".r", ".sql", ".html", ".css", ".js"}
        items.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "icon": "📁" if entry.is_dir() else FILE_ICONS.get(ext, "📄"),
            "size": format_size(stat.st_size) if entry.is_file() else "",
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "path": rel,
            "uploader": meta.get("uploader", ""),
            "previewable": ext in PREVIEW_EXTS and entry.is_file() and stat.st_size < 50_000_000,
            "preview_type": "image" if is_image else ("pdf" if is_pdf else ("text" if is_text else "")),
        })

    breadcrumbs = [{"name": "공유폴더", "path": ""}]
    parts = [p for p in path.split("/") if p]
    for i, part in enumerate(parts):
        breadcrumbs.append({"name": part, "path": "/".join(parts[:i+1])})

    return render(request, "files.html", {
        "page": "files",
        "items": items,
        "current_path": path,
        "breadcrumbs": breadcrumbs,
        "parent_path": "/".join(parts[:-1]) if parts else None,
    })


MAX_UPLOAD_SIZE = 50 * 1024 * 1024


@app.post("/files/upload/{path:path}")
@app.post("/files/upload")
async def upload_files(request: Request, path: str = ""):
    target = safe_path(path)
    if not target.is_dir():
        raise HTTPException(400, "폴더가 아닙니다")
    pid = get_profile_id(request)
    form = await request.form()
    files = form.getlist("files")
    with get_db() as conn:
        profile = conn.execute("SELECT name, emoji FROM work_profiles WHERE id=?", (pid,)).fetchone()
        uploader = f'{profile["emoji"]} {profile["name"]}' if profile else ""
        for f in files:
            if hasattr(f, "filename") and f.filename:
                fname = Path(f.filename).name
                if fname.startswith("."):
                    continue
                dest = target / fname
                if dest.exists():
                    stem = dest.stem
                    suffix = dest.suffix
                    counter = 1
                    while dest.exists():
                        dest = target / f"{stem}_{counter}{suffix}"
                        counter += 1
                    fname = dest.name
                content = await f.read()
                if len(content) > MAX_UPLOAD_SIZE:
                    raise HTTPException(413, f"파일 크기 초과 (최대 50MB): {fname}")
                dest.write_bytes(content)
                file_rel = f"{path}/{fname}".lstrip("/") if path else fname
                conn.execute("INSERT INTO file_uploads (file_path, uploader) VALUES (?, ?)", (file_rel, uploader))
    return redirect(request, f"/files/{path}" if path else "/files")


@app.post("/files/mkdir/{path:path}")
@app.post("/files/mkdir")
async def make_directory(request: Request, path: str = "", folder_name: str = Form(...)):
    target = safe_path(path)
    if not target.is_dir():
        raise HTTPException(400)
    folder_name = fix_mojibake(folder_name).strip().replace("/", "_").replace("..", "_")
    if not folder_name:
        raise HTTPException(400)
    new_dir = target / folder_name
    new_dir.mkdir(exist_ok=True)
    return redirect(request, f"/files/{path}" if path else "/files")


@app.post("/files/delete/{path:path}")
async def delete_file(request: Request, path: str):
    get_profile_id(request)
    target = safe_path(path)
    if not target.exists():
        raise HTTPException(404)
    if target == SHARED_ROOT.resolve():
        raise HTTPException(403, "루트 폴더는 삭제할 수 없습니다")
    if target.is_file():
        target.unlink()
        with get_db() as conn:
            conn.execute("DELETE FROM file_uploads WHERE file_path=?", (path,))
    elif target.is_dir():
        import shutil
        shutil.rmtree(target)
        with get_db() as conn:
            conn.execute("DELETE FROM file_uploads WHERE file_path LIKE ?", (path + "/%",))
    parent = "/".join(path.split("/")[:-1])
    return redirect(request, f"/files/{parent}" if parent else "/files")


# ── Reminders API ──


# ── Review ──


# ── Service Worker (root scope) ──


# ── Health check ──


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
