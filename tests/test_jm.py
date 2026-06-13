"""
JM Planner automated tests (50 cases).

Categories:
  - Page rendering (10)
  - CRUD operations (12)
  - Edge cases (8)
  - HTMX partial (8)
  - Security headers (5)
  - Performance (2)
  - API endpoints (5)

Run:
  cd /workspace/app/planners && python3 -m pytest tests/test_jm.py -v --tb=short
"""

import time
import sys
sys.path.insert(0, "/workspace/app/planners/jm")

from fastapi.testclient import TestClient
from conftest import jm_app

client = TestClient(jm_app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════════════════
# Page Rendering (10)
# ═══════════════════════════════════════════════════════════════════════════

def test_dashboard():
    """GET / -- dashboard page responds 200."""
    r = client.get("/")
    assert r.status_code == 200


def test_todos_page():
    r = client.get("/todos")
    assert r.status_code == 200


def test_calendar_page():
    r = client.get("/calendar")
    assert r.status_code == 200


def test_today_page():
    r = client.get("/today")
    assert r.status_code == 200


def test_timetable_page():
    r = client.get("/timetable")
    assert r.status_code == 200


def test_habits_page():
    r = client.get("/habits")
    assert r.status_code == 200


def test_settings_page():
    r = client.get("/settings")
    assert r.status_code == 200


def test_achievements_page():
    r = client.get("/achievements")
    assert r.status_code == 200


def test_stats_page():
    r = client.get("/stats")
    assert r.status_code == 200


def test_search_page():
    r = client.get("/search")
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# API Endpoints (5)
# ═══════════════════════════════════════════════════════════════════════════

def test_api_quick_add():
    r = client.post(
        "/api/quick-add",
        json={"title": "테스트 할일"},
        headers={"origin": "http://testserver", "host": "testserver"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True


def test_api_achievements_check():
    r = client.get("/api/achievements/check")
    assert r.status_code == 200


def test_api_push_vapid_key():
    r = client.get("/api/push/vapid-key")
    assert r.status_code == 200


def test_api_export_todos():
    r = client.get("/api/export/todos")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "text/csv" in ct or "application/octet-stream" in ct or "text/" in ct


def test_api_reminders():
    r = client.get("/api/reminders")
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# CRUD Operations (12)
# ═══════════════════════════════════════════════════════════════════════════

def test_crud_create_todo():
    """POST /todos -- create a todo with form data."""
    r = client.post("/todos", data={"title": "테스트할일"}, follow_redirects=False)
    assert r.status_code in (200, 303)


def test_crud_toggle_todo():
    """POST /todos -- create, then toggle the created todo."""
    # Create a todo first
    client.post("/todos", data={"title": "토글테스트"}, follow_redirects=True)
    # Find the todo ID from the export
    export = client.get("/api/export/todos")
    # Toggle todo id=1 (first created in test DB)
    r = client.post("/todos/1/toggle", follow_redirects=False)
    assert r.status_code in (200, 303)


def test_crud_create_subtask():
    """POST /todos/{id}/subtasks -- add a subtask."""
    # Ensure a todo exists
    client.post("/todos", data={"title": "서브태스크부모"}, follow_redirects=True)
    r = client.post("/todos/1/subtasks", data={"title": "서브태스크"}, follow_redirects=False)
    assert r.status_code in (200, 303)


def test_crud_create_category():
    """POST /settings/categories -- create a category."""
    r = client.post(
        "/settings/categories",
        data={"name": "테스트카테고리", "color": "#d97706"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)


def test_crud_create_event():
    """POST /events -- create a calendar event."""
    r = client.post(
        "/events",
        data={"title": "테스트일정", "start_time": "2026-06-07T10:00"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)


def test_crud_create_memo():
    """POST /memos -- create a memo."""
    r = client.post(
        "/memos",
        data={"title": "테스트메모", "content": "메모 내용입니다"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)


def test_crud_create_worklog():
    """POST /worklogs -- create a work log."""
    r = client.post(
        "/worklogs",
        data={"title": "테스트업무", "content": "업무 내용", "hours": "1.5"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)


def test_crud_create_dday():
    """POST /ddays -- create a d-day."""
    r = client.post(
        "/ddays",
        data={"title": "테스트디데이", "target_date": "2026-12-31"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)


def test_crud_create_link():
    """POST /links -- create a link."""
    r = client.post(
        "/links",
        data={"title": "테스트링크", "url": "https://example.com"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)


def test_crud_create_habit():
    """POST /habits -- create a habit."""
    r = client.post(
        "/habits",
        data={"name": "테스트습관"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)


def test_crud_export_habits():
    """GET /api/export/habits -- CSV export."""
    r = client.get("/api/export/habits")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "text/csv" in ct or "text/" in ct


def test_crud_export_worklogs():
    """GET /api/export/worklogs -- CSV export."""
    r = client.get("/api/export/worklogs")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "text/csv" in ct or "text/" in ct


# ═══════════════════════════════════════════════════════════════════════════
# Edge Cases (8)
# ═══════════════════════════════════════════════════════════════════════════

def test_edge_calendar_extreme_values():
    """GET /calendar with extreme year/month -- should clamp, not crash."""
    r = client.get("/calendar?year=99999&month=13")
    assert r.status_code == 200  # clamped in-place, not redirect


def test_edge_quick_add_empty_title():
    """POST /api/quick-add with empty title -- should return 400."""
    r = client.post(
        "/api/quick-add",
        json={"title": ""},
        headers={"origin": "http://testserver", "host": "testserver"},
    )
    assert r.status_code == 400


def test_edge_quick_add_nlp_tomorrow():
    """POST /api/quick-add with NLP date -- due_date should be parsed."""
    r = client.post(
        "/api/quick-add",
        json={"title": "내일 보고서"},
        headers={"origin": "http://testserver", "host": "testserver"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("due_date") is not None


def test_edge_quick_add_nlp_time():
    """POST /api/quick-add with time expression -- title parsed."""
    r = client.post(
        "/api/quick-add",
        json={"title": "오후 3시 회의"},
        headers={"origin": "http://testserver", "host": "testserver"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True


def test_edge_nonexistent_page():
    """GET /nonexistent-page -- should return 404 or 405."""
    r = client.get("/nonexistent-page")
    assert r.status_code in (404, 405)


def test_edge_export_worklogs():
    """GET /api/export/worklogs -- CSV format."""
    r = client.get("/api/export/worklogs")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "csv" in ct or "text/" in ct


def test_edge_import_todos_empty():
    """POST /api/import/todos with no file -- should return 400."""
    r = client.post(
        "/api/import/todos",
        data={},
        follow_redirects=False,
    )
    assert r.status_code in (400, 422)


def test_edge_todos_pagination():
    """GET /todos with page/per_page params -- should not crash."""
    r = client.get("/todos?page=1&per_page=5")
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# HTMX Partial (8)
# ═══════════════════════════════════════════════════════════════════════════

def test_htmx_dashboard_partial():
    """HTMX partial for dashboard -- no full HTML document."""
    r = client.get("/", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<!DOCTYPE" not in r.text


def test_htmx_todos_partial():
    r = client.get("/todos", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<!DOCTYPE" not in r.text


def test_htmx_calendar_partial():
    r = client.get("/calendar", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<!DOCTYPE" not in r.text


def test_htmx_habits_partial():
    r = client.get("/habits", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<!DOCTYPE" not in r.text


def test_htmx_worklogs_partial():
    r = client.get("/worklogs", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<!DOCTYPE" not in r.text


def test_htmx_memos_partial():
    r = client.get("/memos", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<!DOCTYPE" not in r.text


def test_htmx_settings_partial():
    r = client.get("/settings", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<!DOCTYPE" not in r.text


def test_htmx_achievements_partial():
    r = client.get("/achievements", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<!DOCTYPE" not in r.text


# ═══════════════════════════════════════════════════════════════════════════
# Security Headers (5)
# ═══════════════════════════════════════════════════════════════════════════

def test_security_header_x_content_type_options():
    r = client.get("/todos")
    assert "X-Content-Type-Options" in r.headers
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_security_header_csp():
    r = client.get("/todos")
    assert "Content-Security-Policy" in r.headers
    csp = r.headers["Content-Security-Policy"]
    assert "script-src" in csp


def test_security_header_x_frame_options():
    """X-Frame-Options should be DENY or SAMEORIGIN."""
    r = client.get("/todos")
    assert "X-Frame-Options" in r.headers
    assert r.headers["X-Frame-Options"] in ("DENY", "SAMEORIGIN")


def test_security_header_referrer_policy():
    """Referrer-Policy header should exist."""
    r = client.get("/todos")
    assert "Referrer-Policy" in r.headers


def test_security_header_csp_on_dashboard():
    """CSP header present on dashboard too."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Content-Security-Policy" in r.headers


# ═══════════════════════════════════════════════════════════════════════════
# Performance (2)
# ═══════════════════════════════════════════════════════════════════════════

def test_perf_dashboard_under_1s():
    """GET / should respond within 1000ms."""
    start = time.time()
    r = client.get("/")
    elapsed = time.time() - start
    assert r.status_code == 200
    assert elapsed < 1.0, f"Dashboard took {elapsed:.2f}s"


def test_perf_todos_under_1s():
    """GET /todos should respond within 1000ms."""
    start = time.time()
    r = client.get("/todos")
    elapsed = time.time() - start
    assert r.status_code == 200
    assert elapsed < 1.0, f"Todos took {elapsed:.2f}s"
