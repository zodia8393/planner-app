import sqlite3
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest

from conftest import jm_app, my_app


ORIGIN = {"origin": "http://test", "host": "test"}


@contextmanager
def _failing_db():
    raise sqlite3.OperationalError("simulated todo list fetch failure")
    yield


async def _setup_my_profile(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/setup",
        data={"name": f"FetchError{uuid4().hex[:8]}"},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303


def _assert_todo_fetch_error_state(html: str, expected_retry_url: str) -> None:
    escaped_retry_url = expected_retry_url.replace("&", "&amp;")

    assert 'id="todo-list-error"' in html
    assert 'role="alert"' in html
    assert 'aria-live="assertive"' in html
    assert 'aria-atomic="true"' in html
    assert 'aria-labelledby="todo-list-error-title"' in html
    assert 'aria-describedby="todo-list-error-desc"' in html
    assert "할일 목록을 불러올 수 없습니다" in html
    assert "할일 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요." in html
    assert 'id="todo-list-retry"' in html
    assert 'aria-label="할일 목록 다시 시도"' in html
    assert f'href="{escaped_retry_url}"' in html
    assert f'hx-get="{escaped_retry_url}"' in html
    assert 'hx-target="#todoPage"' in html
    assert 'hx-swap="outerHTML"' in html
    assert "다시 시도" in html
    assert 'id="addForm"' in html
    assert 'id="todoList"' in html


@pytest.mark.asyncio
async def test_jm_core_todo_list_fetch_error_renders_retry_state(jm: httpx.AsyncClient, monkeypatch):
    monkeypatch.setattr(jm_app.state, "get_db", _failing_db)

    response = await jm.get("/todos?filter=active&energy=2")

    assert response.status_code == 503
    _assert_todo_fetch_error_state(response.text, "http://test/todos?filter=active&energy=2")


@pytest.mark.asyncio
async def test_my_core_todo_list_fetch_error_renders_retry_state(my: httpx.AsyncClient, monkeypatch):
    await _setup_my_profile(my)
    monkeypatch.setattr(my_app.state, "get_db", _failing_db)

    response = await my.get("/todos?filter=active&energy=2")

    assert response.status_code == 503
    _assert_todo_fetch_error_state(response.text, "http://test/todos?filter=active&energy=2")
