"""
CRUD integration tests for all 3 planner apps.

Covers: todo, memo, worklog, notice, event — full create/read/update/delete cycles.
Each app uses an isolated temporary DB (shared via conftest.py).

Run:  cd /workspace/app/planners && python3 -m pytest tests/crud_test.py -v
"""

import httpx
import pytest
import pytest_asyncio

from conftest import jm_app, my_app, work_app

ORIGIN = {"origin": "http://test", "host": "test"}

# Fixture `jm` is provided by conftest.py


@pytest_asyncio.fixture
async def my_authed():
    """My planner client with planner_profile cookie set."""
    transport = httpx.ASGITransport(app=my_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/setup", data={"name": "CRUDUser"}, headers=ORIGIN, follow_redirects=False)
        cookie = _extract_cookie(r, "planner_profile")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=my_app),
            base_url="http://test",
            cookies={"planner_profile": cookie},
        ) as authed:
            yield authed


@pytest_asyncio.fixture
async def work_authed():
    """Work planner client with work_profile cookie set."""
    transport = httpx.ASGITransport(app=work_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/profiles", data={"name": "CRUDWorker", "emoji": "W"}, headers=ORIGIN, follow_redirects=False)
        r = await c.post("/select-profile", data={"profile_id": "1"}, headers=ORIGIN, follow_redirects=False)
        cookie = _extract_cookie(r, "work_profile")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=work_app),
            base_url="http://test",
            cookies={"work_profile": cookie},
        ) as authed:
            yield authed


def _extract_cookie(response: httpx.Response, name: str) -> str:
    for part in response.headers.get("set-cookie", "").split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part.split("=", 1)[1]
    raise ValueError(f"Cookie {name} not found")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _location_id(response: httpx.Response) -> str:
    """Extract numeric ID from redirect Location header (e.g. /todos → last created)."""
    loc = response.headers.get("location", "")
    parts = [p for p in loc.split("/") if p.isdigit()]
    return parts[-1] if parts else ""


# ═══════════════════════════════════════════════════════════════════════════
# Todo CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestTodoCRUD:

    @pytest.mark.asyncio
    async def test_jm_todo_lifecycle(self, jm: httpx.AsyncClient):
        await self._todo_lifecycle(jm)

    @pytest.mark.asyncio
    async def test_my_todo_lifecycle(self, my_authed: httpx.AsyncClient):
        await self._todo_lifecycle(my_authed)

    @pytest.mark.asyncio
    async def test_work_todo_lifecycle(self, work_authed: httpx.AsyncClient):
        await self._todo_lifecycle(work_authed)

    async def _todo_lifecycle(self, c: httpx.AsyncClient):
        import re
        # Create
        r = await c.post("/todos", data={"title": "CRUD test todo", "priority": "2"}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303), f"Create failed: {r.status_code}"

        # Read list & find ID
        r = await c.get("/todos")
        assert r.status_code == 200
        assert "CRUD test todo" in r.text
        ids = re.findall(r'/todos/(\d+)/edit', r.text)
        assert ids, "No todo edit link found"
        tid = ids[-1]

        # Edit form
        r = await c.get(f"/todos/{tid}/edit")
        assert r.status_code == 200

        # Update
        r = await c.put(f"/todos/{tid}", data={"title": "Updated todo", "priority": "1"}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Verify update
        r = await c.get("/todos")
        assert "Updated todo" in r.text

        # Toggle complete
        r = await c.post(f"/todos/{tid}/toggle", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Delete
        r = await c.delete(f"/todos/{tid}", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Verify deleted
        r = await c.get(f"/todos/{tid}/edit")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Subtask CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestSubtaskCRUD:

    @pytest.mark.asyncio
    async def test_jm_subtask_lifecycle(self, jm: httpx.AsyncClient):
        await self._subtask_lifecycle(jm)

    @pytest.mark.asyncio
    async def test_my_subtask_lifecycle(self, my_authed: httpx.AsyncClient):
        await self._subtask_lifecycle(my_authed)

    @pytest.mark.asyncio
    async def test_work_subtask_lifecycle(self, work_authed: httpx.AsyncClient):
        await self._subtask_lifecycle(work_authed)

    async def _subtask_lifecycle(self, c: httpx.AsyncClient):
        # Create parent todo first
        r = await c.post("/todos", data={"title": "SubtaskParent"}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Find the parent todo ID from the list page
        r = await c.get("/todos")
        import re
        ids = re.findall(r'data-todo-id="(\d+)"', r.text)
        assert ids, "No todo found on page"
        parent_id = ids[-1]

        # Create subtask
        r = await c.post(f"/todos/{parent_id}/subtasks", data={"title": "Sub item"}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Find the subtask ID
        r = await c.get("/todos")
        sub_ids = re.findall(r'data-subtask-id="(\d+)"', r.text)
        if not sub_ids:
            sub_ids = re.findall(r'/subtasks/(\d+)/', r.text)
        assert sub_ids, "No subtask found on page"
        sub_id = sub_ids[-1]

        # Toggle subtask
        r = await c.post(f"/subtasks/{sub_id}/toggle", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Delete subtask
        r = await c.delete(f"/subtasks/{sub_id}", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)


# ═══════════════════════════════════════════════════════════════════════════
# Memo CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestMemoCRUD:

    @pytest.mark.asyncio
    async def test_jm_memo_lifecycle(self, jm: httpx.AsyncClient):
        await self._memo_lifecycle(jm)

    @pytest.mark.asyncio
    async def test_my_memo_lifecycle(self, my_authed: httpx.AsyncClient):
        await self._memo_lifecycle(my_authed)

    @pytest.mark.asyncio
    async def test_work_memo_lifecycle(self, work_authed: httpx.AsyncClient):
        await self._memo_lifecycle(work_authed)

    async def _memo_lifecycle(self, c: httpx.AsyncClient):
        import re
        # Create
        r = await c.post("/memos", data={"content": "Test memo content"}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Read list & find ID
        r = await c.get("/memos")
        assert r.status_code == 200
        assert "Test memo content" in r.text
        ids = re.findall(r'/memos/(\d+)/edit', r.text)
        assert ids, "No memo edit link found"
        mid = ids[-1]

        # Edit form
        r = await c.get(f"/memos/{mid}/edit")
        assert r.status_code == 200

        # Update
        r = await c.put(f"/memos/{mid}", data={"content": "Updated memo"}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Verify update
        r = await c.get("/memos")
        assert "Updated memo" in r.text

        # Delete
        r = await c.delete(f"/memos/{mid}", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)


# ═══════════════════════════════════════════════════════════════════════════
# Notice CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestNoticeCRUD:

    @pytest.mark.asyncio
    async def test_jm_notice_lifecycle(self, jm: httpx.AsyncClient):
        await self._notice_lifecycle(jm)

    @pytest.mark.asyncio
    async def test_my_notice_lifecycle(self, my_authed: httpx.AsyncClient):
        await self._notice_lifecycle(my_authed)

    @pytest.mark.asyncio
    async def test_work_notice_lifecycle(self, work_authed: httpx.AsyncClient):
        await self._notice_lifecycle(work_authed)

    async def _notice_lifecycle(self, c: httpx.AsyncClient):
        import re
        # Create
        r = await c.post("/notices", data={"title": "Test notice", "content": "Notice body"}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Read list & find ID
        r = await c.get("/notices")
        assert r.status_code == 200
        assert "Test notice" in r.text
        ids = re.findall(r'/notices/(\d+)/edit', r.text)
        assert ids, "No notice edit link found"
        nid = ids[-1]

        # Edit form
        r = await c.get(f"/notices/{nid}/edit")
        assert r.status_code == 200

        # Update
        r = await c.put(f"/notices/{nid}", data={"title": "Updated notice", "content": "New body"}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Pin toggle
        r = await c.post(f"/notices/{nid}/pin", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Delete
        r = await c.delete(f"/notices/{nid}", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)


# ═══════════════════════════════════════════════════════════════════════════
# Event CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestEventCRUD:

    @pytest.mark.asyncio
    async def test_jm_event_lifecycle(self, jm: httpx.AsyncClient):
        await self._event_lifecycle(jm)

    @pytest.mark.asyncio
    async def test_my_event_lifecycle(self, my_authed: httpx.AsyncClient):
        await self._event_lifecycle(my_authed)

    @pytest.mark.asyncio
    async def test_work_event_lifecycle(self, work_authed: httpx.AsyncClient):
        await self._event_lifecycle(work_authed)

    async def _event_lifecycle(self, c: httpx.AsyncClient):
        # Calendar page
        r = await c.get("/calendar")
        assert r.status_code == 200

        # Create event (start_time/end_time are datetime strings)
        r = await c.post("/events", data={
            "title": "Test event",
            "start_time": "2026-06-01T10:00",
            "end_time": "2026-06-01T11:00",
        }, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Find the event ID by probing edit endpoints
        eid = None
        for probe_id in range(1, 200):
            r = await c.get(f"/events/{probe_id}/edit")
            if r.status_code == 200:
                eid = probe_id
                break
        assert eid is not None, "Could not find created event"

        # Update
        r = await c.put(f"/events/{eid}", data={
            "title": "Updated event",
            "start_time": "2026-06-01T14:00",
            "end_time": "2026-06-01T15:00",
        }, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Delete
        r = await c.delete(f"/events/{eid}", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Verify deleted
        r = await c.get(f"/events/{eid}/edit")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Worklog CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestWorklogCRUD:

    @pytest.mark.asyncio
    async def test_jm_worklog_lifecycle(self, jm: httpx.AsyncClient):
        await self._worklog_lifecycle(jm)

    @pytest.mark.asyncio
    async def test_my_worklog_lifecycle(self, my_authed: httpx.AsyncClient):
        await self._worklog_lifecycle(my_authed)

    @pytest.mark.asyncio
    async def test_work_worklog_lifecycle(self, work_authed: httpx.AsyncClient):
        await self._worklog_lifecycle(work_authed)

    async def _worklog_lifecycle(self, c: httpx.AsyncClient):
        # Create
        r = await c.post("/worklogs", data={
            "title": "Test worklog",
            "content": "Did some testing work",
            "log_date": "2026-05-19",
            "hours": "2",
        }, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Read the dated list where the created worklog is shown.
        r = await c.get(r.headers.get("location") or "/worklogs?date=2026-05-19")
        assert r.status_code == 200

        # Find worklog ID
        import re
        ids = re.findall(r'/worklogs/(\d+)/edit', r.text)
        assert ids, "No worklog found on page"
        wl_id = ids[-1]

        # Edit form
        r = await c.get(f"/worklogs/{wl_id}/edit")
        assert r.status_code == 200

        # Update
        r = await c.put(f"/worklogs/{wl_id}", data={
            "title": "Updated worklog",
            "content": "Updated worklog entry",
            "log_date": "2026-05-19",
            "hours": "3",
        }, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Delete
        r = await c.delete(f"/worklogs/{wl_id}", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)


# ═══════════════════════════════════════════════════════════════════════════
# Category CRUD (settings)
# ═══════════════════════════════════════════════════════════════════════════

class TestCategoryCRUD:

    @pytest.mark.asyncio
    async def test_jm_category_lifecycle(self, jm: httpx.AsyncClient):
        await self._category_lifecycle(jm)

    @pytest.mark.asyncio
    async def test_my_category_lifecycle(self, my_authed: httpx.AsyncClient):
        await self._category_lifecycle(my_authed)

    @pytest.mark.asyncio
    async def test_work_category_lifecycle(self, work_authed: httpx.AsyncClient):
        await self._category_lifecycle(work_authed)

    async def _category_lifecycle(self, c: httpx.AsyncClient):
        # Settings page
        r = await c.get("/settings")
        assert r.status_code == 200

        # Create category
        r = await c.post("/settings/categories", data={"name": "TestCat", "color": "#ff0000"}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)

        # Verify on settings page
        r = await c.get("/settings")
        assert "TestCat" in r.text

        # Delete
        r = await c.delete("/settings/categories/1", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (200, 303)


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases / boundary tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBulkActions:

    @pytest.mark.asyncio
    async def test_jm_bulk_complete(self, jm: httpx.AsyncClient):
        for i in range(3):
            await jm.post("/todos", data={"title": f"bulk{i}", "due_date": "2026-06-01"}, headers=ORIGIN, follow_redirects=False)
        r = await jm.get("/todos")
        import re
        ids = re.findall(r'data-todo-id="(\d+)"', r.text)
        assert len(ids) >= 3
        pick = ids[-3:]
        r = await jm.post("/todos/bulk", json={"action": "complete", "ids": pick})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_jm_bulk_delete(self, jm: httpx.AsyncClient):
        await jm.post("/todos", data={"title": "delme1", "due_date": "2026-06-01"}, headers=ORIGIN, follow_redirects=False)
        await jm.post("/todos", data={"title": "delme2", "due_date": "2026-06-01"}, headers=ORIGIN, follow_redirects=False)
        r = await jm.get("/todos")
        import re
        ids = re.findall(r'data-todo-id="(\d+)"', r.text)
        pick = ids[-2:]
        r = await jm.post("/todos/bulk", json={"action": "delete", "ids": pick})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_bulk_invalid_action(self, jm: httpx.AsyncClient):
        r = await jm.post("/todos/bulk", json={"action": "nope", "ids": ["1"]})
        assert r.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_bulk_empty_ids(self, jm: httpx.AsyncClient):
        r = await jm.post("/todos/bulk", json={"action": "complete", "ids": []})
        assert r.json()["ok"] is False


class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_jm_empty_title_todo(self, jm: httpx.AsyncClient):
        r = await jm.post("/todos", data={"title": ""}, headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (303, 400, 422)

    @pytest.mark.asyncio
    async def test_jm_nonexistent_memo_edit(self, jm: httpx.AsyncClient):
        r = await jm.get("/memos/99999/edit")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_jm_nonexistent_event_edit(self, jm: httpx.AsyncClient):
        r = await jm.get("/events/99999/edit")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_jm_nonexistent_notice_edit(self, jm: httpx.AsyncClient):
        r = await jm.get("/notices/99999/edit")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_jm_nonexistent_worklog_edit(self, jm: httpx.AsyncClient):
        r = await jm.get("/worklogs/99999/edit")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_jm_delete_nonexistent_todo(self, jm: httpx.AsyncClient):
        r = await jm.delete("/todos/99999", headers=ORIGIN, follow_redirects=False)
        assert r.status_code in (303, 404)

    @pytest.mark.asyncio
    async def test_work_unauthenticated_crud(self):
        """Without cookie, CRUD routes should redirect to /select-profile.
        Note: /calendar starts with /cal which is in PUBLIC_PATHS, so it's exempt."""
        transport = httpx.ASGITransport(app=work_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            for path in ["/todos", "/memos", "/worklogs", "/notices"]:
                r = await c.get(path, follow_redirects=False)
                assert r.status_code == 303, f"{path} should redirect when unauthenticated"

    @pytest.mark.asyncio
    async def test_my_unauthenticated_crud(self):
        """Without cookie, all CRUD routes should redirect to /setup."""
        transport = httpx.ASGITransport(app=my_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            for path in ["/todos", "/memos", "/calendar", "/worklogs", "/notices"]:
                r = await c.get(path, follow_redirects=False)
                assert r.status_code == 303, f"{path} should redirect when unauthenticated"
