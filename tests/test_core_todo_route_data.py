from uuid import uuid4

import httpx
import pytest

from conftest import jm_app, jm_mod, my_app, my_mod


ORIGIN = {"origin": "http://test", "host": "test"}


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
            (profile_id, title, description, 1, "2026-06-12", '["mvp-route"]', max_order + 1),
        )
        return int(cur.lastrowid)


def _clear_todos_for_profile(mod, profile_id: int) -> None:
    with mod.get_db() as conn:
        todo_ids = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM todos WHERE profile_id=?",
                (profile_id,),
            ).fetchall()
        ]
        if todo_ids:
            placeholders = ",".join("?" for _ in todo_ids)
            conn.execute(f"DELETE FROM subtasks WHERE todo_id IN ({placeholders})", todo_ids)
        conn.execute("DELETE FROM todos WHERE profile_id=?", (profile_id,))


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


def _assert_existing_todo_is_rendered(
    html: str,
    todo_id: int,
    title: str,
    description: str,
    expected_tag: str = "mvp-route",
) -> None:
    assert "업무 관리" in html
    assert title in html
    assert description in html
    assert f'id="todo-{todo_id}"' in html
    assert f'hx-get="/todos/{todo_id}/edit"' in html
    assert expected_tag in html


def _assert_existing_todo_is_loaded_into_edit_ui(
    html: str,
    todo_id: int,
    title: str,
    description: str,
) -> None:
    assert f'id="todo-{todo_id}"' in html
    assert f'id="editTodoForm-{todo_id}"' in html
    assert f'hx-put="/todos/{todo_id}"' in html
    assert f'id="todo-edit-title-{todo_id}" type="text" name="title" value="{title}"' in html
    assert f">{description}</textarea>" in html
    assert 'name="due_date" aria-label="마감일" value="2026-06-12"' in html
    assert '<option value="1" selected>높음</option>' in html
    assert 'name="tags" aria-label="태그" value="mvp-route"' in html


def _assert_create_response_reflects_todo(
    html: str,
    row,
    title: str,
    description: str,
) -> None:
    _assert_existing_todo_is_rendered(
        html,
        int(row["id"]),
        title,
        description,
        expected_tag="mvp-create-response",
    )
    assert 'id="todoList"' in html
    assert 'id="addForm"' in html
    assert 'aria-label="새 업무 제목"' in html


def _assert_core_todo_empty_state(html: str) -> None:
    assert "업무 관리" in html
    assert 'id="todoList"' in html
    assert 'id="todo-empty-state"' in html
    assert 'class="empty-state"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert "업무가 없습니다" in html
    assert "첫 할일을 추가해보세요" in html
    assert 'data-action="scroll-to-add-form"' in html
    assert 'data-form-id="addForm"' in html
    assert 'aria-label="새 할일 입력 폼으로 이동"' in html
    assert "할일 추가하기" in html
    assert 'id="addForm"' in html
    assert 'action="/todos"' in html
    assert 'aria-label="새 업무 제목"' in html


def _assert_get_todos_route_is_registered(app) -> None:
    matches = [
        route
        for route in app.routes
        if getattr(route, "path", "") == "/todos"
        and "GET" in getattr(route, "methods", set())
    ]

    assert len(matches) == 1


def _assert_core_todo_list_view_shell(html: str) -> None:
    assert "업무 관리" in html
    assert 'id="todoPage"' in html
    assert 'id="todoList"' in html
    assert 'id="addForm"' in html
    assert 'action="/todos"' in html
    assert 'hx-post="/todos"' in html
    assert 'href="/todos/kanban"' in html
    assert 'aria-label="새 업무 제목"' in html


@pytest.mark.asyncio
async def test_jm_core_todo_list_route_is_registered_and_renders_list_view_shell(
    jm: httpx.AsyncClient,
):
    _assert_get_todos_route_is_registered(jm_app)

    response = await jm.get("/todos")

    assert response.status_code == 200
    _assert_core_todo_list_view_shell(response.text)


@pytest.mark.asyncio
async def test_my_core_todo_list_route_is_registered_and_renders_list_view_shell(
    my: httpx.AsyncClient,
):
    await _setup_my_profile(my, f"MvpRouteShell{uuid4().hex[:10]}")
    _assert_get_todos_route_is_registered(my_app)

    response = await my.get("/todos")

    assert response.status_code == 200
    _assert_core_todo_list_view_shell(response.text)


@pytest.mark.asyncio
async def test_jm_core_todo_list_route_renders_empty_state_when_no_todos(jm: httpx.AsyncClient):
    _clear_todos_for_profile(jm_mod, 1)

    response = await jm.get("/todos")

    assert response.status_code == 200
    _assert_core_todo_empty_state(response.text)
    assert 'id="todo-"' not in response.text


@pytest.mark.asyncio
async def test_my_core_todo_list_route_renders_empty_state_when_no_todos(my: httpx.AsyncClient):
    profile_name = f"MvpEmptyRoute{uuid4().hex[:10]}"
    profile_id = await _setup_my_profile(my, profile_name)
    _clear_todos_for_profile(my_mod, profile_id)

    response = await my.get("/todos")

    assert response.status_code == 200
    _assert_core_todo_empty_state(response.text)
    assert 'id="todo-"' not in response.text


@pytest.mark.asyncio
async def test_jm_core_todo_list_route_returns_existing_todo_data(jm: httpx.AsyncClient):
    title = f"JM existing MVP todo {uuid4().hex}"
    description = "Existing jm route data should render on the core todo list."
    todo_id = _insert_existing_todo(jm_mod, 1, title, description)

    response = await jm.get("/todos")

    assert response.status_code == 200
    _assert_existing_todo_is_rendered(response.text, todo_id, title, description)


@pytest.mark.asyncio
async def test_jm_core_todo_edit_route_loads_existing_todo_data_into_edit_ui(jm: httpx.AsyncClient):
    title = f"JM editable MVP todo {uuid4().hex}"
    description = "Existing jm route data should load into the edit controls."
    todo_id = _insert_existing_todo(jm_mod, 1, title, description)

    response = await jm.get(
        f"/todos/{todo_id}/edit",
        headers={**ORIGIN, "HX-Request": "true"},
    )

    assert response.status_code == 200
    _assert_existing_todo_is_loaded_into_edit_ui(response.text, todo_id, title, description)


@pytest.mark.asyncio
async def test_my_core_todo_edit_route_loads_existing_todo_data_into_edit_ui(my: httpx.AsyncClient):
    profile_name = f"MvpEditLoad{uuid4().hex[:10]}"
    profile_id = await _setup_my_profile(my, profile_name)
    title = f"My editable MVP todo {uuid4().hex}"
    description = "Existing my route data should load into the edit controls."
    todo_id = _insert_existing_todo(my_mod, profile_id, title, description)

    response = await my.get(
        f"/todos/{todo_id}/edit",
        headers={**ORIGIN, "HX-Request": "true"},
    )

    assert response.status_code == 200
    _assert_existing_todo_is_loaded_into_edit_ui(response.text, todo_id, title, description)


@pytest.mark.asyncio
async def test_jm_core_todo_create_submit_persists_valid_todo(jm: httpx.AsyncClient):
    title = f"JM create MVP todo {uuid4().hex}"
    description = "Submitted through the core todo creation handler."

    response = await jm.post(
        "/todos",
        data={
            "title": title,
            "description": description,
            "due_date": "2026-06-12",
            "priority": "1",
            "tags": "mvp-create, route",
            "assignee": "JM",
            "energy_level": "3",
        },
        headers=ORIGIN,
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/todos"

    row = _fetch_todo_by_title(jm_mod, 1, title)
    assert row is not None
    assert row["description"] == description
    assert row["due_date"] == "2026-06-12"
    assert row["priority"] == 1
    assert row["assignee"] == "JM"
    assert row["energy_level"] == 3
    assert row["completed"] == 0
    assert row["tags"] == '["mvp-create", "route"]'

    list_response = await jm.get("/todos")
    assert list_response.status_code == 200
    _assert_existing_todo_is_rendered(
        list_response.text,
        int(row["id"]),
        title,
        description,
        expected_tag="mvp-create",
    )


@pytest.mark.asyncio
async def test_jm_core_todo_create_submit_final_response_reflects_new_todo(jm: httpx.AsyncClient):
    title = f"JM reflected MVP todo {uuid4().hex}"
    description = "The final create response should render the new jm todo in the list."

    response = await jm.post(
        "/todos",
        data={
            "title": title,
            "description": description,
            "due_date": "2026-06-12",
            "priority": "1",
            "tags": "mvp-create-response, route",
            "assignee": "JM",
            "energy_level": "3",
        },
        headers=ORIGIN,
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert str(response.url).endswith("/todos")

    row = _fetch_todo_by_title(jm_mod, 1, title)
    assert row is not None
    _assert_create_response_reflects_todo(response.text, row, title, description)


@pytest.mark.asyncio
async def test_my_core_todo_create_submit_persists_valid_todo(my: httpx.AsyncClient):
    profile_name = f"MvpCreate{uuid4().hex[:10]}"
    profile_id = await _setup_my_profile(my, profile_name)
    title = f"My create MVP todo {uuid4().hex}"
    description = "Submitted through the my core todo creation handler."

    response = await my.post(
        "/todos",
        data={
            "title": title,
            "description": description,
            "due_date": "2026-06-12",
            "priority": "1",
            "tags": "mvp-create, route",
            "assignee": "MY",
            "energy_level": "3",
        },
        headers=ORIGIN,
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/todos"

    row = _fetch_todo_by_title(my_mod, profile_id, title)
    assert row is not None
    assert row["description"] == description
    assert row["due_date"] == "2026-06-12"
    assert row["priority"] == 1
    assert row["assignee"] == "MY"
    assert row["energy_level"] == 3
    assert row["completed"] == 0
    assert row["tags"] == '["mvp-create", "route"]'

    list_response = await my.get("/todos")
    assert list_response.status_code == 200
    _assert_existing_todo_is_rendered(
        list_response.text,
        int(row["id"]),
        title,
        description,
        expected_tag="mvp-create",
    )


@pytest.mark.asyncio
async def test_my_core_todo_create_submit_final_response_reflects_new_todo(my: httpx.AsyncClient):
    profile_name = f"MvpCreateResponse{uuid4().hex[:10]}"
    profile_id = await _setup_my_profile(my, profile_name)
    title = f"My reflected MVP todo {uuid4().hex}"
    description = "The final create response should render the new my todo in the list."

    response = await my.post(
        "/todos",
        data={
            "title": title,
            "description": description,
            "due_date": "2026-06-12",
            "priority": "1",
            "tags": "mvp-create-response, route",
            "assignee": "MY",
            "energy_level": "3",
        },
        headers=ORIGIN,
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert str(response.url).endswith("/todos")

    row = _fetch_todo_by_title(my_mod, profile_id, title)
    assert row is not None
    _assert_create_response_reflects_todo(response.text, row, title, description)


async def _assert_existing_todo_update_persists(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    instance_label: str,
) -> None:
    original_title = f"{instance_label} original MVP todo {uuid4().hex}"
    original_description = "Existing todo before the edit save flow."
    todo_id = _insert_existing_todo(mod, profile_id, original_title, original_description)
    updated_title = f"{instance_label} updated MVP todo {uuid4().hex}"
    updated_description = "Saved through the core todo edit handler."

    edit_response = await client.get(f"/todos/{todo_id}/edit")
    assert edit_response.status_code == 200
    assert original_title in edit_response.text
    assert f'hx-put="/todos/{todo_id}"' in edit_response.text

    response = await client.put(
        f"/todos/{todo_id}",
        data={
            "title": updated_title,
            "description": updated_description,
            "due_date": "2026-06-13",
            "priority": "3",
            "tags": "mvp-update, route",
            "assignee": instance_label.upper(),
            "energy_level": "1",
        },
        headers=ORIGIN,
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/todos"

    row = _fetch_todo_by_id(mod, profile_id, todo_id)
    assert row is not None
    assert row["title"] == updated_title
    assert row["description"] == updated_description
    assert row["due_date"] == "2026-06-13"
    assert row["priority"] == 3
    assert row["assignee"] == instance_label.upper()
    assert row["energy_level"] == 1
    assert row["tags"] == '["mvp-update", "route"]'

    list_response = await client.get("/todos")
    assert list_response.status_code == 200
    assert original_title not in list_response.text
    _assert_existing_todo_is_rendered(
        list_response.text,
        todo_id,
        updated_title,
        updated_description,
        expected_tag="mvp-update",
    )


async def _assert_existing_todo_htmx_update_shows_success_feedback(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    instance_label: str,
) -> None:
    original_title = f"{instance_label} htmx original MVP todo {uuid4().hex}"
    todo_id = _insert_existing_todo(mod, profile_id, original_title, "Before HTMX edit save.")
    updated_title = f"{instance_label} htmx updated MVP todo {uuid4().hex}"
    updated_description = "Saved through the HTMX edit response."

    response = await client.put(
        f"/todos/{todo_id}",
        data={
            "title": updated_title,
            "description": updated_description,
            "due_date": "2026-06-13",
            "priority": "2",
            "tags": "mvp-update-feedback, route",
            "assignee": instance_label.upper(),
            "energy_level": "2",
        },
        headers={**ORIGIN, "HX-Request": "true"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert f'id="todo-{todo_id}"' in response.text
    assert updated_title in response.text
    assert updated_description in response.text
    assert original_title not in response.text
    assert "변경사항이 저장되었습니다." in response.text
    assert 'role="status"' in response.text
    assert 'aria-live="polite"' in response.text
    assert 'aria-atomic="true"' in response.text

    row = _fetch_todo_by_id(mod, profile_id, todo_id)
    assert row is not None
    assert row["title"] == updated_title
    assert row["description"] == updated_description


@pytest.mark.asyncio
async def test_jm_core_todo_update_submit_persists_existing_todo(jm: httpx.AsyncClient):
    await _assert_existing_todo_update_persists(jm, jm_mod, 1, "jm")


@pytest.mark.asyncio
async def test_jm_core_todo_htmx_update_response_shows_success_feedback(jm: httpx.AsyncClient):
    await _assert_existing_todo_htmx_update_shows_success_feedback(jm, jm_mod, 1, "jm")


@pytest.mark.asyncio
async def test_my_core_todo_update_submit_persists_existing_todo(my: httpx.AsyncClient):
    profile_name = f"MvpUpdate{uuid4().hex[:10]}"
    profile_id = await _setup_my_profile(my, profile_name)

    await _assert_existing_todo_update_persists(my, my_mod, profile_id, "my")


@pytest.mark.asyncio
async def test_my_core_todo_htmx_update_response_shows_success_feedback(my: httpx.AsyncClient):
    profile_name = f"MvpUpdateFeedback{uuid4().hex[:10]}"
    profile_id = await _setup_my_profile(my, profile_name)

    await _assert_existing_todo_htmx_update_shows_success_feedback(my, my_mod, profile_id, "my")


@pytest.mark.asyncio
async def test_my_core_todo_list_route_returns_existing_todo_data(my: httpx.AsyncClient):
    profile_name = f"MvpRoute{uuid4().hex[:10]}"
    profile_id = await _setup_my_profile(my, profile_name)
    title = f"My existing MVP todo {uuid4().hex}"
    description = "Existing my route data should render on the core todo list."
    todo_id = _insert_existing_todo(my_mod, profile_id, title, description)

    response = await my.get("/todos")

    assert response.status_code == 200
    _assert_existing_todo_is_rendered(response.text, todo_id, title, description)
