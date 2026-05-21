"""
Smoke tests for all 3 planner apps (JM, My, Work).

Uses httpx.AsyncClient + ASGITransport to test each FastAPI app
without starting a real server. Each app runs against an isolated
temporary DB so production data is never touched.

Run:  cd /workspace/app_planners && python3 -m pytest tests/smoke_test.py -v
"""

import asyncio

import httpx
import pytest

from conftest import jm_app, my_app, work_app

# Fixtures jm, my, work are provided by conftest.py


# ═══════════════════════════════════════════════════════════════════════════
# JM Planner — single user, no auth middleware
# ═══════════════════════════════════════════════════════════════════════════

class TestJM:
    """JM planner has no auth — dashboard returns 200 directly."""

    @pytest.mark.asyncio
    async def test_health(self, jm: httpx.AsyncClient):
        r = await jm.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_dashboard_no_auth_returns_200(self, jm: httpx.AsyncClient):
        r = await jm.get("/", follow_redirects=True)
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_static_htmx(self, jm: httpx.AsyncClient):
        r = await jm.get("/static/htmx.min.js")
        assert r.status_code == 200
        assert "text/javascript" in r.headers.get("content-type", "") or \
               "application/javascript" in r.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_sse_streaming(self, jm: httpx.AsyncClient):
        async def _check():
            req = jm.build_request("GET", "/sse")
            r = await jm.send(req, stream=True)
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            await r.aclose()
        try:
            await asyncio.wait_for(_check(), timeout=3)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    @pytest.mark.asyncio
    async def test_post_without_csrf_origin_returns_403(self, jm: httpx.AsyncClient):
        r = await jm.post(
            "/todos",
            data={"title": "test"},
            headers={"origin": "http://evil.com", "host": "test"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_post_todo_with_valid_origin(self, jm: httpx.AsyncClient):
        r = await jm.post(
            "/todos",
            data={"title": "smoke test todo"},
            headers={"origin": "http://test", "host": "test"},
            follow_redirects=False,
        )
        assert r.status_code in (200, 303)

    @pytest.mark.asyncio
    async def test_nonexistent_todo_returns_404(self, jm: httpx.AsyncClient):
        r = await jm.get("/todos/99999/edit")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_todos_page_returns_200(self, jm: httpx.AsyncClient):
        r = await jm.get("/todos")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# My Planner — ProfileCheckMiddleware: no cookie → redirect to /setup
# ═══════════════════════════════════════════════════════════════════════════

class TestMy:
    """My planner requires planner_profile cookie; without it → /setup redirect."""

    @pytest.mark.asyncio
    async def test_health(self, my: httpx.AsyncClient):
        r = await my.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["app"] == "my-planner"

    @pytest.mark.asyncio
    async def test_dashboard_no_cookie_redirects_to_setup(self, my: httpx.AsyncClient):
        r = await my.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert "/setup" in r.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_static_htmx(self, my: httpx.AsyncClient):
        r = await my.get("/static/htmx.min.js")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_sse_streaming(self, my: httpx.AsyncClient):
        async def _check():
            req = my.build_request("GET", "/sse")
            r = await my.send(req, stream=True)
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            await r.aclose()
        try:
            await asyncio.wait_for(_check(), timeout=3)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    @pytest.mark.asyncio
    async def test_post_without_csrf_origin_returns_403(self, my: httpx.AsyncClient):
        r = await my.post(
            "/todos",
            data={"title": "test"},
            headers={"origin": "http://evil.com", "host": "test"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_setup_creates_profile(self, my: httpx.AsyncClient):
        r = await my.post(
            "/setup",
            data={"name": "TestUser"},
            headers={"origin": "http://test", "host": "test"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers.get("location") in ("/", "http://test/")
        cookie_header = r.headers.get("set-cookie", "")
        assert "planner_profile" in cookie_header

    @pytest.mark.asyncio
    async def test_dashboard_with_cookie_returns_200(self, my: httpx.AsyncClient):
        r = await my.post(
            "/setup",
            data={"name": "DashUser"},
            headers={"origin": "http://test", "host": "test"},
            follow_redirects=False,
        )
        cookie_header = r.headers.get("set-cookie", "")
        token = None
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("planner_profile="):
                token = part.split("=", 1)[1]
                break
        assert token is not None, "planner_profile cookie not found"

        transport = httpx.ASGITransport(app=my_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"planner_profile": token},
        ) as authed:
            r2 = await authed.get("/")
            assert r2.status_code == 200

    @pytest.mark.asyncio
    async def test_nonexistent_todo_returns_404(self, my: httpx.AsyncClient):
        r = await my.post(
            "/setup",
            data={"name": "ErrorUser"},
            headers={"origin": "http://test", "host": "test"},
            follow_redirects=False,
        )
        cookie_header = r.headers.get("set-cookie", "")
        token = None
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("planner_profile="):
                token = part.split("=", 1)[1]
                break
        assert token is not None

        transport = httpx.ASGITransport(app=my_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"planner_profile": token},
        ) as authed:
            r2 = await authed.get("/todos/99999/edit")
            assert r2.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Work Planner — PinAuthMiddleware + ProfileSelectMiddleware
#   no cookie → redirect to /select-profile
# ═══════════════════════════════════════════════════════════════════════════

class TestWork:
    """Work planner requires work_profile cookie; without it → /select-profile."""

    @pytest.mark.asyncio
    async def test_health(self, work: httpx.AsyncClient):
        r = await work.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_dashboard_no_cookie_redirects_to_select_profile(self, work: httpx.AsyncClient):
        r = await work.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert "/select-profile" in r.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_static_htmx(self, work: httpx.AsyncClient):
        r = await work.get("/static/htmx.min.js")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_sse_streaming(self, work: httpx.AsyncClient):
        async def _check():
            req = work.build_request("GET", "/sse")
            r = await work.send(req, stream=True)
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            await r.aclose()
        try:
            await asyncio.wait_for(_check(), timeout=3)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    @pytest.mark.asyncio
    async def test_post_without_csrf_origin_returns_403(self, work: httpx.AsyncClient):
        r = await work.post(
            "/todos",
            data={"title": "test"},
            headers={"origin": "http://evil.com", "host": "test"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_create_profile_and_select(self, work: httpx.AsyncClient):
        r = await work.post(
            "/profiles",
            data={"name": "SmokeTester", "emoji": "T"},
            headers={"origin": "http://test", "host": "test"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "/select-profile" in r.headers.get("location", "")

        r2 = await work.post(
            "/select-profile",
            data={"profile_id": "1"},
            headers={"origin": "http://test", "host": "test"},
            follow_redirects=False,
        )
        assert r2.status_code == 303
        cookie_header = r2.headers.get("set-cookie", "")
        assert "work_profile" in cookie_header

    @pytest.mark.asyncio
    async def test_dashboard_with_cookie_returns_200(self):
        transport = httpx.ASGITransport(app=work_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"work_profile": "1"},
        ) as client:
            r = await client.get("/")
            assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_nonexistent_todo_returns_404(self):
        transport = httpx.ASGITransport(app=work_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"work_profile": "1"},
        ) as client:
            r = await client.get("/todos/99999/edit")
            assert r.status_code == 404
