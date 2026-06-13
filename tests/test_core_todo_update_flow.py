import sqlite3
from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import pytest

from conftest import jm_mod, my_mod


ORIGIN = {"origin": "http://test", "host": "test"}


class _FailingConnection:
    def __init__(self, conn, sql_prefix: str) -> None:
        self._conn = conn
        self._sql_prefix = sql_prefix

    def execute(self, sql: str, *args, **kwargs):
        if " ".join(sql.split()).upper().startswith(self._sql_prefix):
            raise sqlite3.OperationalError("simulated todo save failure")
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


@contextmanager
def _db_failing_on_sql(mod, sql_prefix: str):
    with mod.get_db() as conn:
        yield _FailingConnection(conn, sql_prefix)


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._current = {key: value or "" for key, value in attrs}
        self._current["text"] = ""

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None:
            self._current["text"] = " ".join(self._current["text"].split())
            self.anchors.append(self._current)
            self._current = None


async def _setup_my_profile(client: httpx.AsyncClient, name: str) -> int:
    response = await client.post(
        "/setup",
        data={"name": name},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303

    with my_mod.get_db() as conn:
        row = conn.execute("SELECT id FROM profiles WHERE name=?", (name,)).fetchone()
    assert row is not None
    return int(row["id"])


def _core_entry_path(html: str) -> str:
    parser = _AnchorCollector()
    parser.feed(html)
    matches = [
        anchor["href"]
        for anchor in parser.anchors
        if anchor.get("href") == "/todos#new" and "할일 추가" in anchor.get("text", "")
    ]

    assert matches == ["/todos#new"]
    parsed = urlsplit(matches[0])
    return urlunsplit(("", "", parsed.path, parsed.query, ""))


def _insert_existing_todo(mod, profile_id: int, title: str, description: str) -> int:
    with mod.get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM todos WHERE profile_id=?",
            (profile_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO todos (
                profile_id, title, description, priority, due_date, tags, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (profile_id, title, description, 1, "2026-06-12", '["mvp-update-flow"]', max_order + 1),
        )
        return int(cur.lastrowid)


def _fetch_todo_by_id(mod, profile_id: int, todo_id: int):
    with mod.get_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM todos
            WHERE profile_id=? AND id=?
            """,
            (profile_id, todo_id),
        ).fetchone()


def _todo_update_unit(app):
    for route in app.routes:
        if getattr(route, "path", "") == "/todos/{todo_id}" and "PUT" in getattr(route, "methods", set()):
            return route.endpoint.__globals__["_apply_todo_update"]
    raise AssertionError("PUT /todos/{todo_id} route was not registered")


def _assert_update_unit_validates_and_applies_changes(mod, profile_id: int, instance_label: str) -> None:
    update_unit = _todo_update_unit(mod.app)
    untouched_id = _insert_existing_todo(
        mod,
        profile_id,
        f"{instance_label} untouched profile todo {uuid4().hex}",
        "This non-target row must not be updated.",
    )
    todo_id = _insert_existing_todo(
        mod,
        profile_id,
        f"{instance_label} unit original MVP todo {uuid4().hex}",
        "Before direct update unit.",
    )

    with mod.get_db() as conn:
        result = update_unit(
            conn,
            mod.app.state,
            todo_id,
            profile_id,
            title=f"  {instance_label} unit updated MVP todo {uuid4().hex}  ",
            description="Saved by the direct update processing unit.",
            due_date="not-a-date",
            priority=99,
            category_id="not-a-category",
            tags="mvp-unit, saved",
            repeat_type="none",
            recurrence_end="not-a-date",
            assignee=f"  {instance_label.upper()}  ",
            energy_level=9,
            reminder_offsets="[]",
        )

    assert result["updated"] == 1
    assert result["title"].startswith(f"{instance_label} unit updated MVP todo")
    assert result["title"] == result["title"].strip()
    assert set(result["changes"]) == {"title", "description", "due_date", "priority"}

    row = _fetch_todo_by_id(mod, profile_id, todo_id)
    assert row is not None
    assert row["title"] == result["title"]
    assert row["description"] == "Saved by the direct update processing unit."
    assert row["due_date"] is None
    assert row["priority"] == 3
    assert row["category_id"] is None
    assert row["tags"] == '["mvp-unit", "saved"]'
    assert row["recurrence_end"] == ""
    assert row["assignee"] == f"  {instance_label.upper()}  "
    assert row["energy_level"] == 3
    assert row["reminder_offsets"] is None

    untouched = _fetch_todo_by_id(mod, profile_id, untouched_id)
    assert untouched is not None
    assert untouched["description"] == "This non-target row must not be updated."

    with mod.get_db() as conn:
        try:
            update_unit(
                conn,
                mod.app.state,
                todo_id,
                profile_id,
                title="   ",
                description="This invalid edit must not be applied.",
            )
        except ValueError as exc:
            assert str(exc) == "제목은 필수입니다"
        else:
            raise AssertionError("blank todo title should fail validation")

    row_after_invalid = _fetch_todo_by_id(mod, profile_id, todo_id)
    assert row_after_invalid is not None
    assert row_after_invalid["title"] == result["title"]
    assert row_after_invalid["description"] == "Saved by the direct update processing unit."


async def _assert_core_update_flow(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    instance_label: str,
) -> None:
    original_title = f"{instance_label} full-flow original MVP todo {uuid4().hex}"
    original_description = "Existing todo before dashboard-to-edit flow."
    todo_id = _insert_existing_todo(mod, profile_id, original_title, original_description)
    updated_title = f"{instance_label} full-flow updated MVP todo {uuid4().hex}"
    updated_description = "Changed and saved through the selected core todo flow."

    dashboard = await client.get("/")
    assert dashboard.status_code == 200
    core_path = _core_entry_path(dashboard.text)

    list_before = await client.get(core_path)
    assert list_before.status_code == 200
    assert f'id="todo-{todo_id}"' in list_before.text
    assert original_title in list_before.text
    assert original_description in list_before.text
    assert f'hx-get="/todos/{todo_id}/edit"' in list_before.text

    edit_response = await client.get(
        f"/todos/{todo_id}/edit",
        headers={**ORIGIN, "HX-Request": "true"},
    )
    assert edit_response.status_code == 200
    assert f'id="editTodoForm-{todo_id}"' in edit_response.text
    assert f'hx-put="/todos/{todo_id}"' in edit_response.text
    assert f'hx-indicator="#todo-edit-loading-{todo_id}"' in edit_response.text
    assert f'id="todo-edit-title-{todo_id}"' in edit_response.text
    assert f'id="todo-edit-loading-{todo_id}"' in edit_response.text
    assert f'id="todo-edit-validation-{todo_id}"' in edit_response.text
    assert 'todo-edit-loading htmx-indicator' in edit_response.text
    assert 'aria-label="할일 제목"' in edit_response.text
    assert f'aria-describedby="todo-edit-validation-{todo_id}"' in edit_response.text
    assert 'aria-label="설명"' in edit_response.text
    assert 'aria-label="마감일"' in edit_response.text
    assert 'aria-label="우선순위"' in edit_response.text
    assert 'aria-label="할일 저장 중"' in edit_response.text
    assert 'role="status"' in edit_response.text
    assert 'aria-live="polite"' in edit_response.text
    assert 'aria-atomic="true"' in edit_response.text
    assert f'aria-describedby="todo-edit-loading-{todo_id}"' in edit_response.text
    assert "할일 제목은 필수입니다." in edit_response.text
    assert "변경사항을 저장하는 중입니다" in edit_response.text
    assert "저장" in edit_response.text

    saved = await client.put(
        f"/todos/{todo_id}",
        data={
            "title": updated_title,
            "description": updated_description,
            "due_date": "2026-06-13",
            "priority": "3",
            "tags": "mvp-update-flow, saved",
            "assignee": instance_label.upper(),
            "energy_level": "1",
        },
        headers={**ORIGIN, "HX-Request": "true"},
        follow_redirects=False,
    )

    assert saved.status_code == 200
    assert f'id="todo-{todo_id}"' in saved.text
    assert updated_title in saved.text
    assert updated_description in saved.text
    assert original_title not in saved.text
    assert "변경사항이 저장되었습니다." in saved.text
    assert 'role="status"' in saved.text
    assert 'aria-live="polite"' in saved.text

    row = _fetch_todo_by_id(mod, profile_id, todo_id)
    assert row is not None
    assert row["title"] == updated_title
    assert row["description"] == updated_description
    assert row["due_date"] == "2026-06-13"
    assert row["priority"] == 3
    assert row["assignee"] == instance_label.upper()
    assert row["energy_level"] == 1
    assert row["tags"] == '["mvp-update-flow", "saved"]'

    list_after = await client.get(core_path)
    assert list_after.status_code == 200
    assert updated_title in list_after.text
    assert updated_description in list_after.text
    assert original_title not in list_after.text


async def _assert_update_success_response_unit(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    instance_label: str,
) -> None:
    original_title = f"{instance_label} response-unit original MVP todo {uuid4().hex}"
    todo_id = _insert_existing_todo(
        mod,
        profile_id,
        original_title,
        "Existing todo before the isolated HTMX save response check.",
    )
    updated_title = f"{instance_label} response-unit saved MVP todo {uuid4().hex}"
    updated_description = "Saved through the isolated HTMX update response unit."

    response = await client.put(
        f"/todos/{todo_id}",
        data={
            "title": updated_title,
            "description": updated_description,
            "due_date": "2026-06-13",
            "priority": "2",
            "tags": "mvp-update-response, saved",
        },
        headers={**ORIGIN, "HX-Request": "true"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert f'id="todo-{todo_id}"' in response.text
    assert f'hx-get="/todos/{todo_id}/edit"' in response.text
    assert f'hx-put="/todos/{todo_id}"' not in response.text
    assert f'id="editTodoForm-{todo_id}"' not in response.text
    assert updated_title in response.text
    assert updated_description in response.text
    assert original_title not in response.text
    assert "변경사항이 저장되었습니다." in response.text
    assert 'class="todo-edit-success focus-accent mb-3 rounded-lg border px-3 py-2 text-sm font-medium"' in response.text
    assert 'role="status"' in response.text
    assert 'aria-live="polite"' in response.text
    assert 'aria-atomic="true"' in response.text
    assert 'aria-label="할일 저장 성공"' in response.text
    assert 'tabindex="0"' in response.text

    row = _fetch_todo_by_id(mod, profile_id, todo_id)
    assert row is not None
    assert row["title"] == updated_title
    assert row["description"] == updated_description
    assert row["tags"] == '["mvp-update-response", "saved"]'


async def _assert_core_update_failure_renders_accessible_feedback(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    instance_label: str,
) -> None:
    original_title = f"{instance_label} failed-update original MVP todo {uuid4().hex}"
    original_description = "Existing todo before a failed edit save."
    todo_id = _insert_existing_todo(mod, profile_id, original_title, original_description)

    failed = await client.put(
        f"/todos/{todo_id}",
        data={
            "title": "   ",
            "description": "This value must not be persisted after validation failure.",
            "due_date": "2026-06-14",
            "priority": "3",
            "tags": "mvp-update-flow, failed",
            "assignee": instance_label.upper(),
            "energy_level": "3",
        },
        headers={**ORIGIN, "HX-Request": "true"},
        follow_redirects=False,
    )

    assert failed.status_code == 400
    assert f'id="todo-{todo_id}"' in failed.text
    assert f'id="editTodoForm-{todo_id}"' in failed.text
    assert f'hx-put="/todos/{todo_id}"' in failed.text
    assert f'id="todo-edit-error-{todo_id}"' in failed.text
    assert 'class="todo-edit-error focus-accent rounded-lg border px-3 py-2 text-sm font-medium"' in failed.text
    assert 'role="alert"' in failed.text
    assert 'aria-live="assertive"' in failed.text
    assert 'aria-atomic="true"' in failed.text
    assert 'tabindex="0"' in failed.text
    assert 'aria-invalid="true"' in failed.text
    assert f'aria-describedby="todo-edit-error-{todo_id} todo-edit-validation-{todo_id}"' in failed.text
    assert f'id="todo-edit-validation-{todo_id}"' in failed.text
    assert "할일 제목은 필수입니다." in failed.text
    assert "제목을 입력해야 저장할 수 있습니다." in failed.text
    assert original_title in failed.text
    assert original_description in failed.text

    row = _fetch_todo_by_id(mod, profile_id, todo_id)
    assert row is not None
    assert row["title"] == original_title
    assert row["description"] == original_description
    assert row["due_date"] == "2026-06-12"
    assert row["priority"] == 1
    assert row["tags"] == '["mvp-update-flow"]'


async def _assert_core_update_save_failure_renders_retry_feedback(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    instance_label: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_title = f"{instance_label} failed-save original MVP todo {uuid4().hex}"
    original_description = "Existing todo before a simulated save failure."
    todo_id = _insert_existing_todo(mod, profile_id, original_title, original_description)

    monkeypatch.setattr(mod.app.state, "get_db", lambda: _db_failing_on_sql(mod, "UPDATE TODOS SET"))
    failed = await client.put(
        f"/todos/{todo_id}",
        data={
            "title": f"{instance_label} failed-save changed title {uuid4().hex}",
            "description": "This update must not be persisted after database failure.",
            "due_date": "2026-06-15",
            "priority": "3",
            "tags": "mvp-update-flow, failed-save",
            "assignee": instance_label.upper(),
            "energy_level": "3",
        },
        headers={**ORIGIN, "HX-Request": "true"},
        follow_redirects=False,
    )

    assert failed.status_code == 503
    assert f'id="todo-{todo_id}"' in failed.text
    assert f'id="editTodoForm-{todo_id}"' in failed.text
    assert f'hx-put="/todos/{todo_id}"' in failed.text
    assert f'id="todo-edit-error-{todo_id}"' in failed.text
    assert 'class="todo-edit-error focus-accent rounded-lg border px-3 py-2 text-sm font-medium"' in failed.text
    assert 'role="alert"' in failed.text
    assert 'aria-live="assertive"' in failed.text
    assert 'aria-atomic="true"' in failed.text
    assert 'aria-label="할일 저장 오류"' in failed.text
    assert 'tabindex="0"' in failed.text
    assert 'aria-label="할일 다시 저장"' in failed.text
    assert f'form="editTodoForm-{todo_id}"' in failed.text
    assert "변경사항을 저장하지 못했습니다. 입력 내용을 확인하고 다시 시도해주세요." in failed.text
    assert "다시 저장" in failed.text
    assert original_title in failed.text
    assert original_description in failed.text

    row = _fetch_todo_by_id(mod, profile_id, todo_id)
    assert row is not None
    assert row["title"] == original_title
    assert row["description"] == original_description
    assert row["due_date"] == "2026-06-12"
    assert row["priority"] == 1
    assert row["tags"] == '["mvp-update-flow"]'


@pytest.mark.asyncio
async def test_jm_core_todo_update_flow_changes_values_and_saves(jm: httpx.AsyncClient):
    await _assert_core_update_flow(jm, jm_mod, 1, "jm")


@pytest.mark.asyncio
async def test_my_core_todo_update_flow_changes_values_and_saves(my: httpx.AsyncClient):
    profile_id = await _setup_my_profile(my, f"MvpUpdateFlow{uuid4().hex[:10]}")

    await _assert_core_update_flow(my, my_mod, profile_id, "my")


@pytest.mark.asyncio
async def test_jm_core_todo_update_success_response_unit_shows_saved_status(jm: httpx.AsyncClient):
    await _assert_update_success_response_unit(jm, jm_mod, 1, "jm")


@pytest.mark.asyncio
async def test_my_core_todo_update_success_response_unit_shows_saved_status(my: httpx.AsyncClient):
    profile_id = await _setup_my_profile(my, f"MvpUpdateResponse{uuid4().hex[:10]}")

    await _assert_update_success_response_unit(my, my_mod, profile_id, "my")


@pytest.mark.asyncio
async def test_jm_core_todo_update_failure_renders_accessible_feedback(jm: httpx.AsyncClient):
    await _assert_core_update_failure_renders_accessible_feedback(jm, jm_mod, 1, "jm")


@pytest.mark.asyncio
async def test_my_core_todo_update_failure_renders_accessible_feedback(my: httpx.AsyncClient):
    profile_id = await _setup_my_profile(my, f"MvpUpdateFail{uuid4().hex[:10]}")

    await _assert_core_update_failure_renders_accessible_feedback(my, my_mod, profile_id, "my")


@pytest.mark.asyncio
async def test_jm_core_todo_update_save_failure_renders_retry_feedback(jm: httpx.AsyncClient, monkeypatch):
    await _assert_core_update_save_failure_renders_retry_feedback(jm, jm_mod, 1, "jm", monkeypatch)


@pytest.mark.asyncio
async def test_my_core_todo_update_save_failure_renders_retry_feedback(my: httpx.AsyncClient, monkeypatch):
    profile_id = await _setup_my_profile(my, f"MvpUpdateSaveFail{uuid4().hex[:10]}")

    await _assert_core_update_save_failure_renders_retry_feedback(my, my_mod, profile_id, "my", monkeypatch)


def test_jm_todo_update_processing_unit_validates_and_applies_changes():
    _assert_update_unit_validates_and_applies_changes(jm_mod, 1, "jm")


def test_my_todo_update_processing_unit_validates_and_applies_changes():
    profile_name = f"MvpUpdateUnit{uuid4().hex[:10]}"
    with my_mod.get_db() as conn:
        cur = conn.execute("INSERT INTO profiles (name) VALUES (?)", (profile_name,))
        profile_id = int(cur.lastrowid)

    _assert_update_unit_validates_and_applies_changes(my_mod, profile_id, "my")
