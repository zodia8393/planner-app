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


class _ElementCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if element_id := attr_map.get("id"):
            self.by_id[element_id] = attr_map


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


def _fetch_todo_by_title(mod, profile_id: int, title: str):
    with mod.get_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM todos
            WHERE profile_id=? AND title=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (profile_id, title),
        ).fetchone()


def _delete_todo_by_title(mod, profile_id: int, title: str) -> None:
    with mod.get_db() as conn:
        conn.execute(
            "DELETE FROM todos WHERE profile_id=? AND title=?",
            (profile_id, title),
        )


def _count_todos(mod, profile_id: int) -> int:
    with mod.get_db() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM todos WHERE profile_id=?",
                (profile_id,),
            ).fetchone()[0]
        )


def _assert_creation_form_is_ready(html: str) -> None:
    parser = _ElementCollector()
    parser.feed(html)
    title_input = parser.by_id["newTodoTitle"]

    assert "업무 관리" in html
    assert 'id="addForm"' in html
    assert 'action="/todos"' in html
    assert 'method="POST"' in html
    assert 'hx-post="/todos"' in html
    assert 'hx-indicator="#todo-create-loading"' in html
    assert 'name="title"' in html
    assert 'aria-label="새 업무 제목"' in html
    assert 'id="todo-create-validation"' in html
    assert "todo-create-validation" in title_input["aria-describedby"].split()
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert "새 업무 제목은 필수입니다." in html
    assert 'name="due_date"' in html
    assert 'aria-label="마감일"' in html
    assert 'name="priority"' in html
    assert 'aria-label="우선순위"' in html
    assert 'name="tags"' in html
    assert 'aria-label="태그"' in html
    assert 'name="description"' in html
    assert 'aria-label="설명"' in html


def _assert_creation_loading_state_contract(html: str) -> None:
    assert 'id="todo-create-loading"' in html
    assert 'todo-create-loading htmx-indicator' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert 'aria-label="할일 추가 중"' in html
    assert 'aria-describedby="todo-create-loading"' in html
    assert "할일을 추가하는 중입니다" in html
    assert html.index('id="todo-create-loading"') < html.index('id="addFormOptions"')


def _assert_created_todo_is_visible(html: str, todo_id: int, title: str, description: str) -> None:
    assert 'id="todoList"' in html
    assert f'id="todo-{todo_id}"' in html
    assert title in html
    assert description in html
    assert "mvp-integration" in html
    assert f'hx-get="/todos/{todo_id}/edit"' in html


def _assert_created_todo_edit_state_is_ready(
    html: str,
    todo_id: int,
    title: str,
    description: str,
) -> None:
    assert f'id="todo-{todo_id}"' in html
    assert f'id="editTodoForm-{todo_id}"' in html
    assert f'hx-put="/todos/{todo_id}"' in html
    assert f'hx-indicator="#todo-edit-loading-{todo_id}"' in html
    assert f'id="todo-edit-title-{todo_id}" type="text" name="title" value="{title}"' in html
    assert f">{description}</textarea>" in html
    assert f'id="todo-edit-validation-{todo_id}"' in html
    assert f'id="todo-edit-loading-{todo_id}"' in html
    assert 'aria-label="할일 제목"' in html
    assert 'aria-label="설명"' in html
    assert 'aria-label="마감일"' in html
    assert 'aria-label="우선순위"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert "저장" in html


def _assert_creation_feedback_is_visible(html: str) -> None:
    assert 'id="todo-create-feedback"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert "할일이 추가되었습니다." in html


def _assert_creation_error_feedback_is_visible(html: str) -> None:
    parser = _ElementCollector()
    parser.feed(html)
    title_input = parser.by_id["newTodoTitle"]

    assert "업무 관리" in html
    assert 'id="addForm"' in html
    assert 'id="todo-create-error"' in html
    assert 'role="alert"' in html
    assert 'aria-live="assertive"' in html
    assert 'aria-atomic="true"' in html
    assert "할일 제목을 입력해주세요." in html
    assert 'aria-invalid="true"' in html
    describedby = title_input["aria-describedby"].split()
    assert "todo-create-error" in describedby
    assert "todo-create-validation" in describedby
    assert 'id="todo-create-validation"' in html
    assert "새 업무 제목은 필수입니다." in html
    assert 'id="todo-create-feedback"' not in html


def _assert_creation_save_error_feedback_is_visible(html: str) -> None:
    assert "업무 관리" in html
    assert 'id="addForm"' in html
    assert 'id="todo-create-error"' in html
    assert 'role="alert"' in html
    assert 'aria-live="assertive"' in html
    assert 'aria-atomic="true"' in html
    assert "할일을 저장하지 못했습니다. 입력 내용을 확인하고 다시 시도해주세요." in html
    assert 'id="addTodoForm"' in html
    assert 'form="addTodoForm"' in html
    assert 'aria-label="할일 추가 다시 저장"' in html
    assert "다시 저장" in html
    assert 'id="todo-create-feedback"' not in html


async def _assert_core_creation_flow(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    instance_label: str,
) -> None:
    title = f"{instance_label} integrated create MVP todo {uuid4().hex}"
    description = f"{instance_label} dashboard to todo list creation flow is reflected."

    try:
        dashboard = await client.get("/")
        assert dashboard.status_code == 200
        core_path = _core_entry_path(dashboard.text)

        list_before = await client.get(core_path)
        assert list_before.status_code == 200
        _assert_creation_form_is_ready(list_before.text)
        _assert_creation_loading_state_contract(list_before.text)
        assert title not in list_before.text

        created = await client.post(
            "/todos",
            data={
                "title": title,
                "description": description,
                "due_date": "2026-06-12",
                "priority": "1",
                "tags": "mvp-integration, create-flow",
                "assignee": instance_label.upper(),
                "energy_level": "3",
            },
            headers=ORIGIN,
            follow_redirects=True,
        )

        assert created.status_code == 200
        assert str(created.url).endswith("/todos")

        row = _fetch_todo_by_title(mod, profile_id, title)
        assert row is not None
        assert row["description"] == description
        assert row["due_date"] == "2026-06-12"
        assert row["priority"] == 1
        assert row["completed"] == 0
        assert row["assignee"] == instance_label.upper()
        assert row["energy_level"] == 3
        assert row["tags"] == '["mvp-integration", "create-flow"]'
        _assert_created_todo_is_visible(created.text, int(row["id"]), title, description)
        _assert_creation_feedback_is_visible(created.text)

        edit_response = await client.get(
            f"/todos/{int(row['id'])}/edit",
            headers={**ORIGIN, "HX-Request": "true"},
        )
        assert edit_response.status_code == 200
        _assert_created_todo_edit_state_is_ready(
            edit_response.text,
            int(row["id"]),
            title,
            description,
        )

        list_after = await client.get(core_path)
        assert list_after.status_code == 200
        _assert_created_todo_is_visible(list_after.text, int(row["id"]), title, description)
        assert 'id="todo-create-feedback"' not in list_after.text
    finally:
        _delete_todo_by_title(mod, profile_id, title)


async def _assert_core_creation_failure_feedback(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
) -> None:
    before_count = _count_todos(mod, profile_id)

    response = await client.post(
        "/todos",
        data={"title": "   ", "description": "must not be saved"},
        headers=ORIGIN,
        follow_redirects=False,
    )

    assert response.status_code in {200, 400}
    _assert_creation_error_feedback_is_visible(response.text)
    assert _count_todos(mod, profile_id) == before_count


async def _assert_core_creation_save_failure_feedback(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_count = _count_todos(mod, profile_id)
    monkeypatch.setattr(mod.app.state, "get_db", lambda: _db_failing_on_sql(mod, "INSERT INTO TODOS"))

    response = await client.post(
        "/todos",
        data={
            "title": f"save failure should not persist {uuid4().hex}",
            "description": "must not be saved when insert fails",
        },
        headers=ORIGIN,
        follow_redirects=False,
    )

    assert response.status_code == 503
    _assert_creation_save_error_feedback_is_visible(response.text)
    assert _count_todos(mod, profile_id) == before_count


@pytest.mark.asyncio
async def test_jm_core_todo_creation_flow_submits_saves_and_reflects(jm: httpx.AsyncClient):
    await _assert_core_creation_flow(jm, jm_mod, 1, "jm")


@pytest.mark.asyncio
async def test_my_core_todo_creation_flow_submits_saves_and_reflects(my: httpx.AsyncClient):
    profile_id = await _setup_my_profile(my, f"MvpCreateFlow{uuid4().hex[:10]}")

    await _assert_core_creation_flow(my, my_mod, profile_id, "my")


@pytest.mark.asyncio
async def test_jm_core_todo_creation_failure_renders_accessible_feedback(jm: httpx.AsyncClient):
    await _assert_core_creation_failure_feedback(jm, jm_mod, 1)


@pytest.mark.asyncio
async def test_my_core_todo_creation_failure_renders_accessible_feedback(my: httpx.AsyncClient):
    profile_id = await _setup_my_profile(my, f"MvpCreateFail{uuid4().hex[:10]}")

    await _assert_core_creation_failure_feedback(my, my_mod, profile_id)


@pytest.mark.asyncio
async def test_jm_core_todo_creation_save_failure_renders_retry_feedback(jm: httpx.AsyncClient, monkeypatch):
    await _assert_core_creation_save_failure_feedback(jm, jm_mod, 1, monkeypatch)


@pytest.mark.asyncio
async def test_my_core_todo_creation_save_failure_renders_retry_feedback(my: httpx.AsyncClient, monkeypatch):
    profile_id = await _setup_my_profile(my, f"MvpCreateSaveFail{uuid4().hex[:10]}")

    await _assert_core_creation_save_failure_feedback(my, my_mod, profile_id, monkeypatch)
