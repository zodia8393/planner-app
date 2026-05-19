"""
Work Planner - Professional task & schedule management
FastAPI + Jinja2 + HTMX + Tailwind CSS + SQLite
"""

import os
import sys
from pathlib import Path as _P
# Add parent directory to sys.path so we can import from common
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
import logging
import shutil
import zipfile
import io
from datetime import datetime, date, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Form, Query, HTTPException, Response, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

import uvicorn

# ── Common module imports ──
from common.utils import fix_mojibake, clamp_priority, validate_date_str, validate_datetime_str, clamp_text
from common.filters import register_filters, render_error_page as _render_error_page, render_worklog_images
from common.middleware import EventBus, CSRFMiddleware, SyncBroadcastMiddleware, patch_formparser_utf8
from common.db import get_db as _common_get_db
from common.image import MAGIC_BYTES, _check_image_magic
from common.gcal import (
    GCAL_CLIENT_ID, GCAL_CLIENT_SECRET, GCAL_SCOPES, GCAL_AUTH_URL,
    GCAL_TOKEN_URL, GCAL_API_BASE,
    gcal_redirect_uri as _gcal_redirect_uri,
    gcal_refresh_token as _common_gcal_refresh_token,
    gcal_fetch_events as _common_gcal_fetch_events,
    gcal_push_event as _common_gcal_push_event,
    gcal_update_event as _common_gcal_update_event,
    gcal_delete_event as _common_gcal_delete_event,
)
from common.excel import parse_excel_with_merges as _parse_excel_with_merges, infer_field_type as _infer_field_type
from common.holidays import KOREAN_HOLIDAYS, get_holidays_for_month


# ── Starlette FormParser latin-1 -> utf-8 patch ──
patch_formparser_utf8()


# ── SSE EventBus (from common) ──
event_bus = EventBus()


# ── Input validation helpers (imported from common.utils) ──




# ── Path setup ──
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "work.db"
(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)


# ── FastAPI app ──
@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

app = FastAPI(title="Work Planner", docs_url=None, redoc_url=None, lifespan=lifespan)


access_logger = logging.getLogger("access")
access_logger.setLevel(logging.INFO)
if not access_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    access_logger.addHandler(_h)


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path == "/sse":
            return response
        client_ip = request.headers.get("fly-client-ip",
                    request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                    or (request.client.host if request.client else "unknown"))
        access_logger.info(
            f"[ACCESS] {client_ip} {request.method} {request.url.path} → {response.status_code}"
        )
        return response


# CSRFMiddleware and SyncBroadcastMiddleware imported from common.middleware

app.add_middleware(SyncBroadcastMiddleware, event_bus=event_bus,
                   skip_paths=("/worklogs/upload-image",),
                   skip_prefixes=("/files/",))
app.add_middleware(CSRFMiddleware)
app.add_middleware(AccessLogMiddleware)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
BG_DIR = BASE_DIR / "data" / "backgrounds"
BG_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/backgrounds", StaticFiles(directory=str(BG_DIR)), name="backgrounds")
WORKLOG_IMG_DIR = BASE_DIR / "data" / "worklog_images"
WORKLOG_IMG_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/worklog-images", StaticFiles(directory=str(WORKLOG_IMG_DIR)), name="worklog_images")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def render(request: Request, name: str, context: dict = None):
    """TemplateResponse wrapper that injects the single profile."""
    ctx = context or {}
    try:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM work_profiles WHERE id=1").fetchone()
            if row:
                ctx["active_profile"] = dict(row)
                ctx["active_profile_id"] = 1
            else:
                ctx["active_profile"] = {"id": 1, "name": "정미", "emoji": "💼", "role": ""}
                ctx["active_profile_id"] = 1
            # Inject background setting
            bg_type = get_user_setting(conn, 1, "bg_type", "none")
            bg_preset = get_user_setting(conn, 1, "bg_preset", "")
            bg_image = get_user_setting(conn, 1, "bg_image", "")
            bg_opacity = get_user_setting(conn, 1, "bg_opacity", "0.7")
            ctx["bg_setting"] = {
                "type": bg_type,
                "preset": bg_preset,
                "image": bg_image,
                "opacity": float(bg_opacity),
            }
    except Exception:
        ctx["active_profile"] = {"id": 1, "name": "정미", "emoji": "💼", "role": ""}
        ctx["active_profile_id"] = 1
        ctx["bg_setting"] = {"type": "none", "preset": "", "image": "", "opacity": 0.7}
    ctx["needs_pin_setup"] = False
    ctx.setdefault("today", date.today())
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


# ── Jinja2 filters (from common.filters) ──
# _render_error_page imported as render_error_page from common.filters


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return HTMLResponse(_render_error_page(404, "페이지를 찾을 수 없습니다"), status_code=404)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return HTMLResponse(_render_error_page(500, "서버 오류가 발생했습니다"), status_code=500)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        if exc.status_code == 404:
            return HTMLResponse(_render_error_page(404, "페이지를 찾을 수 없습니다"), status_code=404)
        raise exc
    return HTMLResponse(_render_error_page(500, "서버 오류가 발생했습니다"), status_code=500)

register_filters(templates)


# ── DB management (wrapper around common.db.get_db) ──
def get_db():
    return _common_get_db(DB_PATH)


def init_db():
    """Initialize DB schema."""
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
            profile_id INTEGER NOT NULL DEFAULT 1,
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

        CREATE TABLE IF NOT EXISTS ddays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            target_date TEXT NOT NULL,
            icon TEXT DEFAULT '🎯',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS work_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 1,
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
            profile_id INTEGER NOT NULL DEFAULT 1,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            priority INTEGER DEFAULT 0,
            pinned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

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
            PRIMARY KEY(profile_id, key)
        );

        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER DEFAULT 1,
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

        CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_date);
        CREATE INDEX IF NOT EXISTS idx_todos_completed ON todos(completed);
        CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);
        CREATE INDEX IF NOT EXISTS idx_work_logs_date ON work_logs(log_date);
        CREATE INDEX IF NOT EXISTS idx_form_entries_template ON form_entries(template_id);
        CREATE INDEX IF NOT EXISTS idx_form_entries_date ON form_entries(entry_date);
        CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
        """)

        for tbl in ("work_profiles", ):
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN role TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
        for tbl in ("todos", "events", "memos", "ddays"):
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN profile_id INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

        # Memo title + category migration
        try:
            conn.execute("ALTER TABLE memos ADD COLUMN title TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE memos ADD COLUMN category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL")
        except sqlite3.OperationalError:
            pass

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

        existing = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if existing == 0:
            conn.executemany(
                "INSERT INTO categories (name, color, sort_order) VALUES (?, ?, ?)",
                [("업무", "#6366f1", 0), ("회의", "#8b5cf6", 1), ("개인", "#10b981", 2), ("기타", "#f59e0b", 3)],
            )

        existing_profiles = conn.execute("SELECT COUNT(*) FROM work_profiles").fetchone()[0]
        if existing_profiles == 0:
            conn.execute(
                "INSERT INTO work_profiles (name, emoji, role) VALUES (?, ?, ?)",
                ("정미", "💼", ""),
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
    """Insert a lightweight audit record. JM is single-user so no profile_id filter."""
    conn.execute(
        "INSERT INTO audit_log (entity_type, entity_id, action, changes_json) VALUES (?,?,?,?)",
        (entity_type, entity_id, action, json.dumps(changes or {}, ensure_ascii=False)),
    )


# ── Utility functions ──
from common.constants import PRIORITY_MAP, REPEAT_MAP, WEEKDAY_NAMES, ROLE_COLORS
from common.recurrence import next_occurrence, expand_recurring_events

# ── Google Calendar OAuth2 (constants and helpers from common.gcal) ──


def _gcal_get_cal_id(profile_id: int) -> str:
    """Look up the calendar_id for a profile from the DB."""
    with get_db() as conn:
        row = conn.execute("SELECT calendar_id FROM gcal_tokens WHERE profile_id=?", (profile_id,)).fetchone()
    return row["calendar_id"] if row else "primary"


async def _gcal_refresh_token(profile_id: int) -> Optional[str]:
    """Refresh and return a valid access token for the given profile."""
    with get_db() as conn:
        return await _common_gcal_refresh_token(conn, profile_id)


async def _gcal_fetch_events(profile_id: int, time_min: str, time_max: str) -> list:
    token = await _gcal_refresh_token(profile_id)
    if not token:
        return []
    cal_id = _gcal_get_cal_id(profile_id)
    return await _common_gcal_fetch_events(token, cal_id, time_min, time_max)


async def _gcal_push_event(profile_id: int, title: str, start_time: str, end_time: str = "") -> str:
    """Create an event in Google Calendar. Returns the gcal event ID or empty string."""
    token = await _gcal_refresh_token(profile_id)
    if not token:
        return ""
    cal_id = _gcal_get_cal_id(profile_id)
    return await _common_gcal_push_event(token, cal_id, title, start_time, end_time)


async def _gcal_update_event(profile_id: int, gcal_id: str, title: str, start_time: str, end_time: str = ""):
    """Update an existing event in Google Calendar."""
    if not gcal_id:
        return
    token = await _gcal_refresh_token(profile_id)
    if not token:
        return
    cal_id = _gcal_get_cal_id(profile_id)
    await _common_gcal_update_event(token, cal_id, gcal_id, title, start_time, end_time)


async def _gcal_delete_event(profile_id: int, gcal_id: str):
    """Delete an event from Google Calendar."""
    if not gcal_id:
        return
    token = await _gcal_refresh_token(profile_id)
    if not token:
        return
    cal_id = _gcal_get_cal_id(profile_id)
    await _common_gcal_delete_event(token, cal_id, gcal_id)


from common.stats import get_stats, get_weekly_chart_data, week_number_in_month, get_week_range


def calc_dday(target_date_str: str) -> int:
    try:
        target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        return (target - date.today()).days
    except (ValueError, TypeError):
        return 0


def get_profile_id(request: Request) -> int:
    return 1


def get_user_setting(conn, profile_id, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM user_settings WHERE profile_id=? AND key=?",
        (str(profile_id), key),
    ).fetchone()
    return row[0] if row else default


def set_user_setting(conn, profile_id, key: str, value: str):
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (profile_id, key, value) VALUES (?, ?, ?)",
        (str(profile_id), key, value),
    )


def redirect(request: Request, url: str):
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def get_profile_name(request: Request) -> str:
    return "정미"


def _run_automation_rules(conn, pid, today_str):
    rules = conn.execute(
        "SELECT * FROM automation_rules WHERE profile_id=? AND enabled=1", (pid,)
    ).fetchall()
    today_date = date.today()
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
app.state.app_name = "jm-planner"
app.state.worklog_img_dir = WORKLOG_IMG_DIR
app.state.get_categories = lambda conn, pid: conn.execute(
    "SELECT * FROM categories ORDER BY sort_order").fetchall()

app.include_router(_r_memos.router)
app.include_router(_r_notices.router)
app.include_router(_r_worklogs.router)
app.include_router(_r_events.router)
app.include_router(_r_todos.router)
app.include_router(_r_forms.router)
app.include_router(_r_settings.router)
app.include_router(_r_misc.router)



# ── Routes: Dashboard ──
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, plan_view: str = "week", plan_offset: int = 0):
    pid = get_profile_id(request)
    today = date.today()
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
            WHERE m.profile_id = ? ORDER BY m.created_at DESC LIMIT 3
        """, (pid,)).fetchall()

        categories = conn.execute("SELECT * FROM categories ORDER BY sort_order").fetchall()

        recent_notices = conn.execute("""
            SELECT * FROM notices ORDER BY pinned DESC, created_at DESC LIMIT 2
        """).fetchall()

        today_worklogs = conn.execute("""
            SELECT wl.*, c.name as category_name, c.color as category_color
            FROM work_logs wl LEFT JOIN categories c ON wl.category_id = c.id
            WHERE wl.log_date = ?
            ORDER BY wl.created_at DESC
        """, (today_str,)).fetchall()
        today_work_hours = sum((dict(l).get("hours", 0) or 0) for l in today_worklogs)

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

        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        time_budgets_raw = conn.execute("""
            SELECT w.category_id, c.name, c.color, COALESCE(SUM(w.hours), 0) as used,
                   COALESCE(tb.weekly_hours, 0) as budget
            FROM work_logs w
            LEFT JOIN categories c ON w.category_id = c.id
            LEFT JOIN time_budgets tb ON tb.category_id = w.category_id AND tb.profile_id = ?
            WHERE w.log_date >= ? AND w.log_date <= ?
            GROUP BY w.category_id
        """, (pid, monday.isoformat(), sunday.isoformat())).fetchall()
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
            month_start = date(y, m, 1)
            month_end = date(y, m, days_in_month)
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
                current_week.append(date(y, m, day_num))
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
            plan_monday = today - timedelta(days=today.weekday()) + timedelta(weeks=plan_offset)
            plan_sunday = plan_monday + timedelta(days=6)
            week_num = week_number_in_month(plan_monday)
            plan_todos = conn.execute("""
                SELECT t.*, c.name as category_name, c.color as category_color
                FROM todos t LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.due_date BETWEEN ? AND ? AND t.profile_id = ?
                ORDER BY t.due_date ASC, t.priority ASC, t.sort_order ASC
            """, (plan_monday.isoformat(), plan_sunday.isoformat(), pid)).fetchall()
            week_days = []
            for i in range(7):
                d = plan_monday + timedelta(days=i)
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
                "nav_label": f"{plan_monday.year}년 {plan_monday.month}월 {week_num}주차 ({plan_monday.strftime('%m.%d')} ~ {plan_sunday.strftime('%m.%d')})",
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
        "recent_notices": [dict(r) for r in recent_notices],
        "today_worklogs": [dict(r) for r in today_worklogs],
        "today_work_hours": today_work_hours,
        "categories": [dict(r) for r in categories],
        "project_progress": [dict(r) for r in project_progress],
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








# ── Korean Holidays (imported from common.holidays) ──


# ── Routes: Calendar ──










# ── Routes: Google Calendar Event Edit/Delete ──

@app.get("/events/gcal/{gcal_id:path}/edit", response_class=HTMLResponse)
async def edit_gcal_event_form(request: Request, gcal_id: str):
    """Fetch a Google Calendar event and return an edit form."""
    pid = get_profile_id(request)
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
                            title: str = Form(...),
                            start_time: str = Form(...),
                            end_time: str = Form(""),
                            memo: str = Form("")):
    pid = get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
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
    pid = get_profile_id(request)
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










# ── Routes: Settings (categories + theme) ──










# ── Routes: Backup & Restore ──




# ── Routes: Google Calendar OAuth ──
@app.get("/settings/gcal/connect")
async def gcal_connect(request: Request):
    if not GCAL_CLIENT_ID:
        raise HTTPException(400, "GCAL_CLIENT_ID 환경변수가 설정되지 않았습니다")
    from urllib.parse import urlencode
    pid = get_profile_id(request)
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
    import httpx
    logger = logging.getLogger("gcal")
    logger.info(f"[GCAL] callback: code={'yes' if code else 'NO'}, error={error}, state={state}")
    if error:
        logger.error(f"[GCAL] Google returned error: {error}")
        raise HTTPException(400, f"Google 인증 오류: {error}")
    if not code:
        logger.error("[GCAL] No code received")
        raise HTTPException(400, "Google 인증 코드가 없습니다")
    pid = int(state) if state.isdigit() else get_profile_id(request)
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
    pid = get_profile_id(request)
    with get_db() as conn:
        conn.execute("DELETE FROM gcal_tokens WHERE profile_id=?", (pid,))
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/gcal/calendar-id")
async def gcal_set_calendar_id(request: Request, calendar_id: str = Form("primary")):
    pid = get_profile_id(request)
    with get_db() as conn:
        conn.execute("UPDATE gcal_tokens SET calendar_id=? WHERE profile_id=?", (calendar_id, pid))
    return RedirectResponse("/settings", status_code=303)


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


# ── Routes: Background Settings ──
ALLOWED_BG_PRESETS = {"gradient-1", "gradient-2", "gradient-3", "gradient-4", "gradient-5", "gradient-6"}
ALLOWED_BG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BG_SIZE = 5 * 1024 * 1024  # 5MB


@app.post("/settings/background", response_class=HTMLResponse)
async def save_background_setting(
    request: Request,
    type: str = Form("none"),
    preset: str = Form(""),
    opacity: float = Form(0.7),
    file: UploadFile = File(None),
):
    pid = get_profile_id(request)
    bg_type = type if type in ("preset", "upload", "none") else "none"
    opacity = max(0.3, min(0.95, opacity))

    with get_db() as conn:
        set_user_setting(conn, pid, "bg_type", bg_type)
        set_user_setting(conn, pid, "bg_opacity", str(opacity))

        if bg_type == "preset" and preset in ALLOWED_BG_PRESETS:
            set_user_setting(conn, pid, "bg_preset", preset)
        elif bg_type == "upload" and file and file.filename:
            ext = Path(file.filename).suffix.lower()
            if ext not in ALLOWED_BG_EXTENSIONS:
                raise HTTPException(400, "허용되지 않는 파일 형식입니다 (jpg, png, webp만 가능)")
            content = await file.read()
            if len(content) > MAX_BG_SIZE:
                raise HTTPException(400, "파일 크기가 5MB를 초과합니다")
            filename = f"bg_{pid}_{uuid.uuid4().hex[:8]}{ext}"
            filepath = BG_DIR / filename
            filepath.write_bytes(content)
            old_image = get_user_setting(conn, pid, "bg_image", "")
            if old_image:
                old_path = BG_DIR / Path(old_image).name
                if old_path.exists():
                    old_path.unlink()
            set_user_setting(conn, pid, "bg_image", filename)
        elif bg_type == "none":
            set_user_setting(conn, pid, "bg_preset", "")

    return redirect(request, "/settings")


@app.get("/api/settings/background")
async def get_background_setting(request: Request):
    pid = get_profile_id(request)
    with get_db() as conn:
        bg_type = get_user_setting(conn, pid, "bg_type", "none")
        bg_preset = get_user_setting(conn, pid, "bg_preset", "")
        bg_image = get_user_setting(conn, pid, "bg_image", "")
        bg_opacity = get_user_setting(conn, pid, "bg_opacity", "0.7")
    return JSONResponse({
        "type": bg_type,
        "preset": bg_preset,
        "image": bg_image,
        "opacity": float(bg_opacity),
    })


# ── Routes: Work Logs ──




# MAGIC_BYTES and _check_image_magic imported from common.image









# ── Routes: Notices ──














# ── Routes: Form Templates (양식) ──




# _parse_excel_with_merges and _infer_field_type imported from common.excel


















# ── Routes: Form Entries (양식 작성) ──












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




# ── Routes: Plans (weekly/monthly) ──




# ── Quick-add from dashboard ──




# ── Routes: Memo view partial ──


# ── iCal Feed (Calendar Subscription) ──


# ── Routes: Audit Log ──


# ── Routes: Search ──


# ── Focus mode ──


# ── Routes: D-day ──
@app.get("/ddays", response_class=HTMLResponse)
async def ddays_page(request: Request):
    pid = get_profile_id(request)
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
async def create_dday(request: Request, title: str = Form(...), target_date: str = Form(...), icon: str = Form("\U0001f3af")):
    pid = get_profile_id(request)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO ddays (profile_id, title, target_date, icon) VALUES (?,?,?,?)",
            (pid, title, target_date, icon or "\U0001f3af"),
        )
    return redirect(request, "/ddays")


@app.delete("/ddays/{dday_id}", response_class=HTMLResponse)
async def delete_dday(request: Request, dday_id: int):
    pid = get_profile_id(request)
    with get_db() as conn:
        conn.execute("DELETE FROM ddays WHERE id=? AND profile_id=?", (dday_id, pid))
    return HTMLResponse("")


# ── Routes: Links ──
@app.get("/links", response_class=HTMLResponse)
async def links_page(request: Request):
    pid = get_profile_id(request)
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
    # Read tunnel data for cross-planner links
    tunnel_data = None
    tunnel_file = BASE_DIR / "tunnel-url.txt"
    if tunnel_file.exists():
        try:
            import json as _json
            text = tunnel_file.read_text().strip()
            if text.startswith("{"):
                tunnel_data = _json.loads(text)
            else:
                tunnel_data = {"jm": {"url": text}}
        except Exception:
            pass
    return render(request, "links.html", {
        "page": "links",
        "links": links,
        "link_categories": categories,
        "tunnel_data": tunnel_data,
        "current_app": "jm",
    })


@app.post("/links", response_class=HTMLResponse)
async def create_link(request: Request, title: str = Form(...), url: str = Form(...),
                      category: str = Form(""), description: str = Form("")):
    if not url.startswith(('http://', 'https://', '/')):
        raise HTTPException(400, detail="유효하지 않은 URL입니다")
    pid = get_profile_id(request)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO links (profile_id, title, url, category, description) VALUES (?,?,?,?,?)",
            (pid, title, url, category, description),
        )
    return redirect(request, "/links")


@app.delete("/links/{link_id}", response_class=HTMLResponse)
async def delete_link(request: Request, link_id: int):
    pid = get_profile_id(request)
    with get_db() as conn:
        conn.execute("DELETE FROM links WHERE id=? AND profile_id=?", (link_id, pid))
    return HTMLResponse("")


# ── Routes: Stats ──
@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    pid = get_profile_id(request)
    with get_db() as conn:
        stats = get_stats(conn, pid)
        chart_data = get_weekly_chart_data(conn, pid)

        # Total counts
        total_all = conn.execute("SELECT COUNT(*) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
        total_completed = conn.execute("SELECT COUNT(*) FROM todos WHERE profile_id=? AND completed=1", (pid,)).fetchone()[0]
        total_rate = round(total_completed / total_all * 100) if total_all > 0 else 0

        # Category stats
        cat_stats = []
        cats = conn.execute("SELECT * FROM categories ORDER BY sort_order").fetchall()
        for c in cats:
            total = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE category_id=? AND profile_id=?", (c["id"], pid)
            ).fetchone()[0]
            done = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE category_id=? AND profile_id=? AND completed=1", (c["id"], pid)
            ).fetchone()[0]
            cat_stats.append({"name": c["name"], "color": c["color"], "total": total, "done": done})

        # Monthly trend
        monthly_data = []
        today = date.today()
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

        # Monthly events
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
        "heatmap_today": date.today().isoformat(),
    })


# ── Routes: Form Entry Stats (JSON) ──


# ── Review ──


# ── Reminders API ──


# ── Service Worker (root scope) ──


# ── Health check ──


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
