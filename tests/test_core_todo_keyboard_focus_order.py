from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from conftest import jm_mod, my_mod


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = {"origin": "http://test", "host": "test"}


class FocusableCollector(HTMLParser):
    FOCUSABLE_TAGS = {"a", "button", "input", "select", "textarea", "summary"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._stack: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        attr["tag"] = tag
        attr["text"] = ""

        if tag == "input":
            if self._is_focusable(attr):
                self.items.append(attr)
            return

        if tag not in self.FOCUSABLE_TAGS and self._is_focusable(attr):
            self.items.append(attr)
            return

        self._stack.append(attr)

    def handle_data(self, data: str) -> None:
        for item in self._stack:
            item["text"] += data

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] != tag:
                continue

            item = self._stack.pop(index)
            if self._is_focusable(item):
                item["text"] = _squash(item["text"])
                self.items.append(item)
            return

    def _is_focusable(self, item: dict[str, str]) -> bool:
        if "disabled" in item:
            return False
        if item["tag"] == "input" and item.get("type") == "hidden":
            return False
        if item.get("tabindex") == "-1":
            return False
        if item.get("aria-hidden") == "true":
            return False

        classes = set(item.get("class", "").split())
        if {"hidden", "sr-only"} & classes:
            return False

        return (
            item["tag"] in self.FOCUSABLE_TAGS
            or "href" in item
            or item.get("role") in {"button", "link"}
            or "tabindex" in item
        )


def _squash(value: str) -> str:
    return " ".join(value.split())


def _focusables(html: str) -> list[dict[str, str]]:
    parser = FocusableCollector()
    parser.feed(html)
    return parser.items


def _label(item: dict[str, str]) -> str:
    return _squash(
        item.get("aria-label")
        or item.get("title")
        or item.get("placeholder")
        or item.get("text")
        or item.get("name")
        or ""
    )


def _index(items: list[dict[str, str]], predicate) -> int:
    for index, item in enumerate(items):
        if predicate(item):
            return index

    labels = [
        {
            "tag": item.get("tag", ""),
            "href": item.get("href", ""),
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "label": _label(item),
        }
        for item in items
    ]
    raise AssertionError(f"focus target not found in {labels}")


def _index_after(items: list[dict[str, str]], after: int, predicate) -> int:
    for index, item in enumerate(items):
        if index <= after:
            continue
        if predicate(item):
            return index

    labels = [
        {
            "tag": item.get("tag", ""),
            "href": item.get("href", ""),
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "label": _label(item),
        }
        for item in items[after + 1 :]
    ]
    raise AssertionError(f"focus target not found after index {after} in {labels}")


def _insert_todo(mod, profile_id: int, title: str) -> int:
    with mod.get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO todos (profile_id, title, description, priority, due_date, tags, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                title,
                "Temporary isolated item for core todo keyboard focus order.",
                1,
                "2026-06-12",
                '["keyboard-focus"]',
                1,
            ),
        )
        return int(cur.lastrowid)


def _fetch_todo_by_id(mod, profile_id: int, todo_id: int):
    with mod.get_db() as conn:
        return conn.execute(
            "SELECT * FROM todos WHERE profile_id=? AND id=?",
            (profile_id, todo_id),
        ).fetchone()


async def _setup_my_profile(client: httpx.AsyncClient) -> int:
    name = f"TodoFocus{uuid4().hex[:8]}"
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


def _assert_core_todo_focus_order(app_name: str, html: str, todo_id: int) -> None:
    items = _focusables(html)

    assert items, f"{app_name}: /todos rendered no keyboard focus targets"
    assert not [
        item
        for item in items
        if item.get("tabindex", "").isdigit() and item["tabindex"] != "0"
    ], f"{app_name}: positive tabindex would override logical document order"
    assert not [
        item
        for item in items
        if item["tag"] in {"a", "button", "input", "select", "textarea", "summary"} and not _label(item)
    ], f"{app_name}: visible focusable controls must have accessible names"

    usage = _index(items, lambda item: item["tag"] == "summary" and "사용법" in _label(item))
    list_view = _index(items, lambda item: item.get("href") == "/todos" and _label(item) == "목록 보기")
    kanban_view = _index(items, lambda item: item.get("href") == "/todos/kanban")
    filter_all = _index(items, lambda item: item.get("href", "").startswith("/todos?filter=all") and _label(item) == "전체")
    filter_active = _index(items, lambda item: item.get("href", "").startswith("/todos?filter=active"))
    filter_completed = _index(items, lambda item: item.get("href", "").startswith("/todos?filter=completed"))
    category_all = _index_after(
        items,
        filter_completed,
        lambda item: item.get("href") == "/todos?filter=all" and _label(item) == "전체",
    )
    bulk = _index(items, lambda item: item.get("id") == "bulkToggle")
    secondary_filters = _index(items, lambda item: item["tag"] == "summary" and "정렬/필터" in _label(item))
    new_title = _index(items, lambda item: item.get("name") == "title" and item.get("aria-label") == "새 업무 제목")
    add_submit = _index(items, lambda item: item["tag"] == "button" and _label(item) == "추가")
    add_cancel = _index(
        items,
        lambda item: item["tag"] == "button"
        and item.get("type") == "reset"
        and _label(item) == "할일 추가 취소",
    )
    add_options = _index(items, lambda item: item["tag"] == "summary" and "옵션 더보기" in _label(item))
    todo_card = _index(items, lambda item: item.get("id") == f"todo-{todo_id}")
    toggle = _index(
        items,
        lambda item: item.get("hx-post") == f"/todos/{todo_id}/toggle"
        and _label(item) == "완료 처리",
    )
    tag = _index_after(items, toggle, lambda item: item.get("href") == "/todos?tag=keyboard-focus")
    subtask = _index(
        items,
        lambda item: item.get("data-action") == "toggle-subtask-form"
        and item.get("data-todo-id") == str(todo_id),
    )
    edit = _index(items, lambda item: item.get("hx-get") == f"/todos/{todo_id}/edit")
    delete = _index(items, lambda item: item.get("hx-delete") == f"/todos/{todo_id}")
    mobile_dashboard = _index(
        items,
        lambda item: item.get("href") == "/"
        and _label(item) == "대시보드"
        and items.index(item) > delete,
    )

    expected_forward = [
        usage,
        list_view,
        kanban_view,
        filter_all,
        filter_active,
        filter_completed,
        category_all,
        bulk,
        secondary_filters,
        new_title,
        add_submit,
        add_cancel,
        add_options,
        todo_card,
        toggle,
        tag,
        subtask,
        edit,
        delete,
        mobile_dashboard,
    ]

    assert expected_forward == sorted(expected_forward), (
        f"{app_name}: /todos Tab order should move from page help and filters "
        "to add form, existing todo actions, then mobile navigation"
    )
    assert list(reversed(expected_forward)) == sorted(expected_forward, reverse=True), (
        f"{app_name}: /todos Shift+Tab order should be the reverse of Tab order"
    )


def _assert_existing_todo_edit_entry_is_keyboard_visible(app_name: str) -> None:
    item_template = (
        ROOT / app_name / "templates" / "partials" / "todo_item.html"
    ).read_text(encoding="utf-8")
    shortcuts_js = (ROOT / app_name / "static" / "shortcuts.js").read_text(encoding="utf-8")
    app_css = (ROOT / app_name / "static" / "css" / "app.css").read_text(encoding="utf-8")

    assert 'data-todo-nav tabindex="0"' in item_template
    assert 'hx-get="/todos/{{ todo.id }}/edit"' in item_template
    assert 'title="편집" aria-label="편집"' in item_template
    assert "if (key === 'Enter' && !e.ctrlKey && !e.metaKey)" in shortcuts_js
    assert 'current.querySelector(\'button[hx-get*="/edit"]\')' in shortcuts_js
    assert "#todoPage [data-todo-nav]:focus-within .todo-action-bar" in app_css
    assert "#todoPage [data-todo-nav]:focus-visible .todo-action-bar" in app_css
    assert "#todoPage .todo-action-bar:focus-within" in app_css
    assert '#todoPage :where(a[href], button, summary, [role="button"], [tabindex]:not([tabindex="-1"])):focus-visible' in app_css
    assert "outline: 3px solid var(--color-accent);" in app_css
    assert "outline-offset: 3px;" in app_css
    assert "box-shadow: 0 0 0 5px var(--color-accent-soft);" in app_css
    assert "opacity: 1 !important;" in app_css


def _assert_creation_required_fields_are_keyboard_input_ready(app_name: str, html: str) -> None:
    items = _focusables(html)

    assert items, f"{app_name}: /todos rendered no keyboard focus targets"
    assert 'action="/todos"' in html
    assert 'method="POST"' in html
    assert 'hx-post="/todos"' in html
    assert not [
        item
        for item in items
        if item.get("tabindex", "").isdigit() and item["tabindex"] != "0"
    ], f"{app_name}: positive tabindex would override keyboard field order"

    title = _index(
        items,
        lambda item: item["tag"] == "input"
        and item.get("id") == "newTodoTitle"
        and item.get("name") == "title",
    )
    submit = _index_after(
        items,
        title,
        lambda item: item["tag"] == "button"
        and item.get("type") == "submit"
        and _label(item) == "추가",
    )
    options = _index_after(
        items,
        submit,
        lambda item: item["tag"] == "summary" and "옵션 더보기" in _label(item),
    )

    required_inputs = [
        item
        for item in items[:submit]
        if item["tag"] in {"input", "select", "textarea"} and "required" in item
    ]

    assert [item.get("name") for item in required_inputs] == ["title"], (
        f"{app_name}: required creation fields should be reachable in order before submit"
    )

    title_input = items[title]
    assert title < submit < options, (
        f"{app_name}: keyboard flow should move from required title field to submit, "
        "then optional creation controls"
    )
    assert title_input.get("type") == "text"
    assert title_input.get("aria-label") == "새 업무 제목"
    assert title_input.get("placeholder")
    assert "required" in title_input
    assert "disabled" not in title_input
    assert "readonly" not in title_input
    assert "hidden" not in set(title_input.get("class", "").split())

    submit_button = items[submit]
    assert submit_button.get("type") == "submit"
    assert "disabled" not in submit_button
    assert "formnovalidate" not in submit_button
    assert submit_button.get("data-action", "") == ""


def _assert_dashboard_create_entry_opens_keyboard_ready_form(
    app_name: str,
    dashboard_html: str,
    todo_html: str,
) -> None:
    dashboard_items = _focusables(dashboard_html)
    entry_index = _index(
        dashboard_items,
        lambda item: item["tag"] == "a"
        and item.get("href") == "/todos#new"
        and _label(item) == "할일 추가 화면으로 이동",
    )
    entry = dashboard_items[entry_index]

    assert entry.get("tabindex", "0") != "-1"
    assert entry.get("aria-hidden") != "true"
    assert "disabled" not in entry

    _assert_creation_required_fields_are_keyboard_input_ready(app_name, todo_html)

    form_items = _focusables(todo_html)
    title_index = _index(
        form_items,
        lambda item: item["tag"] == "input"
        and item.get("id") == "newTodoTitle"
        and item.get("name") == "title",
    )
    title_input = form_items[title_index]

    assert 'id="addForm"' in todo_html
    assert title_input.get("aria-label") == "새 업무 제목"
    assert "hidden" not in set(title_input.get("class", "").split())


def _assert_existing_todo_edit_form_is_keyboard_savable(
    app_name: str,
    html: str,
    todo_id: int,
) -> None:
    items = _focusables(html)

    assert items, f"{app_name}: edit form rendered no keyboard focus targets"
    assert f'id="editTodoForm-{todo_id}"' in html
    assert f'hx-put="/todos/{todo_id}"' in html
    assert f'hx-target="#todo-{todo_id}"' in html
    assert f'hx-indicator="#todo-edit-loading-{todo_id}"' in html
    assert not [
        item
        for item in items
        if item.get("tabindex", "").isdigit() and item["tabindex"] != "0"
    ], f"{app_name}: positive tabindex would override edit form keyboard order"

    cancel_top = _index(
        items,
        lambda item: item["tag"] == "a"
        and item.get("href") == "/todos"
        and _label(item) == "취소",
    )
    title = _index_after(
        items,
        cancel_top,
        lambda item: item["tag"] == "input"
        and item.get("id") == f"todo-edit-title-{todo_id}"
        and item.get("name") == "title",
    )
    description = _index_after(
        items,
        title,
        lambda item: item["tag"] == "textarea" and item.get("name") == "description",
    )
    due_date = _index_after(
        items,
        description,
        lambda item: item["tag"] == "input" and item.get("name") == "due_date",
    )
    priority = _index_after(
        items,
        due_date,
        lambda item: item["tag"] == "select" and item.get("name") == "priority",
    )
    category = _index_after(
        items,
        priority,
        lambda item: item["tag"] == "select" and item.get("name") == "category_id",
    )
    repeat_type = _index_after(
        items,
        category,
        lambda item: item["tag"] == "select" and item.get("name") == "repeat_type",
    )
    energy_level = _index_after(
        items,
        repeat_type,
        lambda item: item["tag"] == "select" and item.get("name") == "energy_level",
    )
    reminder_select = _index_after(
        items,
        energy_level,
        lambda item: item["tag"] == "select"
        and item.get("id") == f"todoOffsetSel_{todo_id}"
        and _label(item) == "알림 시간 선택",
    )
    reminder_add = _index_after(
        items,
        reminder_select,
        lambda item: item["tag"] == "button"
        and item.get("data-action") == "add-edit-todo-offset"
        and item.get("data-todo-id") == str(todo_id),
    )
    default_reminder = _index_after(
        items,
        reminder_add,
        lambda item: item["tag"] == "input"
        and item.get("id") == f"todoUseDefault_{todo_id}"
        and item.get("type") == "checkbox",
    )
    tags = _index_after(
        items,
        default_reminder,
        lambda item: item["tag"] == "input" and item.get("name") == "tags",
    )
    cancel_bottom = _index_after(
        items,
        tags,
        lambda item: item["tag"] == "a"
        and item.get("href") == "/todos"
        and _label(item) == "취소",
    )
    delete = _index_after(
        items,
        cancel_bottom,
        lambda item: item["tag"] == "button"
        and item.get("data-action") == "delete-todo"
        and item.get("hx-delete") == f"/todos/{todo_id}",
    )
    save = _index_after(
        items,
        delete,
        lambda item: item["tag"] == "button"
        and item.get("type") == "submit"
        and item.get("form") == f"editTodoForm-{todo_id}"
        and _label(item) == "저장",
    )

    editable_targets = [
        items[index]
        for index in [
            title,
            description,
            due_date,
            priority,
            category,
            repeat_type,
            energy_level,
            reminder_select,
            default_reminder,
            tags,
            save,
        ]
    ]

    assert [
        cancel_top,
        title,
        description,
        due_date,
        priority,
        category,
        repeat_type,
        energy_level,
        reminder_select,
        reminder_add,
        default_reminder,
        tags,
        cancel_bottom,
        delete,
        save,
    ] == sorted(
        [
            cancel_top,
            title,
            description,
            due_date,
            priority,
            category,
            repeat_type,
            energy_level,
            reminder_select,
            reminder_add,
            default_reminder,
            tags,
            cancel_bottom,
            delete,
            save,
        ]
    ), f"{app_name}: edit form keyboard flow should move through values and actions before Save"
    assert not [
        item
        for item in editable_targets
        if "disabled" in item or "readonly" in item
    ], f"{app_name}: edit fields and Save must stay keyboard-operable"

    title_input = items[title]
    save_button = items[save]
    assert title_input.get("type") == "text"
    assert title_input.get("required") == ""
    assert title_input.get("aria-label") == "할일 제목"
    assert f"todo-edit-validation-{todo_id}" in title_input.get("aria-describedby", "")
    assert items[description].get("aria-label") == "설명"
    assert items[due_date].get("aria-label") == "마감일"
    assert items[priority].get("aria-label") == "우선순위"
    assert items[tags].get("aria-label") == "태그"
    assert items[delete].get("aria-label") == "할일 삭제"
    assert save_button.get("data-action") == "collect-edit-byday"
    assert save_button.get("data-todo-id") == str(todo_id)
    assert save_button.get("aria-describedby") == f"todo-edit-loading-{todo_id}"


@pytest.mark.asyncio
async def test_jm_core_todo_list_keyboard_focus_order_is_logical(jm: httpx.AsyncClient):
    title = f"JM keyboard focus todo {uuid4().hex}"
    todo_id = _insert_todo(jm_mod, 1, title)

    response = await jm.get("/todos")

    assert response.status_code == 200
    assert title in response.text
    _assert_core_todo_focus_order("jm", response.text, todo_id)
    _assert_existing_todo_edit_entry_is_keyboard_visible("jm")


@pytest.mark.asyncio
async def test_my_core_todo_list_keyboard_focus_order_is_logical(my: httpx.AsyncClient):
    profile_id = await _setup_my_profile(my)
    title = f"My keyboard focus todo {uuid4().hex}"
    todo_id = _insert_todo(my_mod, profile_id, title)

    response = await my.get("/todos")

    assert response.status_code == 200
    assert title in response.text
    _assert_core_todo_focus_order("my", response.text, todo_id)
    _assert_existing_todo_edit_entry_is_keyboard_visible("my")


@pytest.mark.asyncio
async def test_jm_core_todo_creation_required_field_accepts_keyboard_entry_in_order(
    jm: httpx.AsyncClient,
):
    response = await jm.get("/todos")

    assert response.status_code == 200
    _assert_creation_required_fields_are_keyboard_input_ready("jm", response.text)


@pytest.mark.asyncio
async def test_my_core_todo_creation_required_field_accepts_keyboard_entry_in_order(
    my: httpx.AsyncClient,
):
    await _setup_my_profile(my)
    response = await my.get("/todos")

    assert response.status_code == 200
    _assert_creation_required_fields_are_keyboard_input_ready("my", response.text)


@pytest.mark.asyncio
async def test_jm_dashboard_create_entry_opens_todo_form_with_keyboard_only(
    jm: httpx.AsyncClient,
):
    dashboard = await jm.get("/")
    todo_list = await jm.get("/todos")

    assert dashboard.status_code == 200
    assert todo_list.status_code == 200
    _assert_dashboard_create_entry_opens_keyboard_ready_form(
        "jm",
        dashboard.text,
        todo_list.text,
    )


@pytest.mark.asyncio
async def test_my_dashboard_create_entry_opens_todo_form_with_keyboard_only(
    my: httpx.AsyncClient,
):
    await _setup_my_profile(my)
    dashboard = await my.get("/")
    todo_list = await my.get("/todos")

    assert dashboard.status_code == 200
    assert todo_list.status_code == 200
    _assert_dashboard_create_entry_opens_keyboard_ready_form(
        "my",
        dashboard.text,
        todo_list.text,
    )


@pytest.mark.asyncio
async def test_jm_existing_todo_edit_form_values_can_be_changed_and_saved_by_keyboard(
    jm: httpx.AsyncClient,
):
    title = f"JM keyboard editable todo {uuid4().hex}"
    todo_id = _insert_todo(jm_mod, 1, title)
    updated_title = f"JM keyboard edited todo {uuid4().hex}"
    updated_description = "Changed via the edit form controls reachable by keyboard."

    edit_response = await jm.get(
        f"/todos/{todo_id}/edit",
        headers={**ORIGIN, "HX-Request": "true"},
    )

    assert edit_response.status_code == 200
    _assert_existing_todo_edit_form_is_keyboard_savable(
        "jm",
        edit_response.text,
        todo_id,
    )

    saved = await jm.put(
        f"/todos/{todo_id}",
        data={
            "title": updated_title,
            "description": updated_description,
            "due_date": "2026-06-13",
            "priority": "3",
            "tags": "keyboard-edit, saved",
            "energy_level": "1",
        },
        headers={**ORIGIN, "HX-Request": "true"},
    )

    assert saved.status_code == 200
    assert updated_title in saved.text
    assert updated_description in saved.text
    assert title not in saved.text

    row = _fetch_todo_by_id(jm_mod, 1, todo_id)
    assert row is not None
    assert row["title"] == updated_title
    assert row["description"] == updated_description
    assert row["due_date"] == "2026-06-13"
    assert row["priority"] == 3
    assert row["energy_level"] == 1
    assert row["tags"] == '["keyboard-edit", "saved"]'


@pytest.mark.asyncio
async def test_my_existing_todo_edit_form_values_can_be_changed_and_saved_by_keyboard(
    my: httpx.AsyncClient,
):
    profile_id = await _setup_my_profile(my)
    title = f"My keyboard editable todo {uuid4().hex}"
    todo_id = _insert_todo(my_mod, profile_id, title)
    updated_title = f"My keyboard edited todo {uuid4().hex}"
    updated_description = "Changed via the edit form controls reachable by keyboard."

    edit_response = await my.get(
        f"/todos/{todo_id}/edit",
        headers={**ORIGIN, "HX-Request": "true"},
    )

    assert edit_response.status_code == 200
    _assert_existing_todo_edit_form_is_keyboard_savable(
        "my",
        edit_response.text,
        todo_id,
    )

    saved = await my.put(
        f"/todos/{todo_id}",
        data={
            "title": updated_title,
            "description": updated_description,
            "due_date": "2026-06-13",
            "priority": "3",
            "tags": "keyboard-edit, saved",
            "energy_level": "1",
        },
        headers={**ORIGIN, "HX-Request": "true"},
    )

    assert saved.status_code == 200
    assert updated_title in saved.text
    assert updated_description in saved.text
    assert title not in saved.text

    row = _fetch_todo_by_id(my_mod, profile_id, todo_id)
    assert row is not None
    assert row["title"] == updated_title
    assert row["description"] == updated_description
    assert row["due_date"] == "2026-06-13"
    assert row["priority"] == 3
    assert row["energy_level"] == 1
    assert row["tags"] == '["keyboard-edit", "saved"]'
