from collections import OrderedDict
from datetime import date
from html import unescape
from pathlib import Path
from uuid import uuid4

import pytest

from common.constants import PRIORITY_MAP, REPEAT_MAP, RRULE_DAY_OPTIONS, RRULE_FREQ_OPTIONS
from conftest import jm_mod, my_mod


ROOT = Path(__file__).resolve().parents[1]


def _todo_context(title: str, description: str, todo_id: int = 4242) -> dict:
    todo = {
        "id": todo_id,
        "title": title,
        "description": description,
        "completed": 0,
        "priority": 1,
        "due_date": "2026-06-12",
        "tags": '["mvp-render"]',
        "energy_level": 2,
        "category_name": "MVP",
        "category_color": "#2563eb",
        "repeat_type": "none",
        "reminder_offsets": "",
        "assignee": "",
        "subtasks": [],
    }
    return {
        "is_htmx": True,
        "page": "todos",
        "todo_groups": OrderedDict([("2026-06-12", [todo])]),
        "todo_count": 1,
        "categories": [{"id": 7, "name": "MVP", "color": "#2563eb"}],
        "current_filter": "all",
        "current_category_id": None,
        "current_assignee": None,
        "current_energy": None,
        "current_tag": None,
        "priority_map": PRIORITY_MAP,
        "repeat_map": REPEAT_MAP,
        "rrule_freq_options": RRULE_FREQ_OPTIONS,
        "rrule_day_options": RRULE_DAY_OPTIONS,
        "rrule_to_korean": lambda value: value,
        "pg_page": 1,
        "pg_per_page": 20,
        "pg_total": 1,
        "pg_total_pages": 1,
        "pg_has_next": False,
        "pg_has_prev": False,
        "pg_filter_qs": "",
        "today": date(2026, 6, 12),
        "config": {"planner_name": "Test Planner"},
    }


def _empty_todo_context() -> dict:
    context = _todo_context("unused empty title", "unused empty description")
    context.update(
        {
            "todo_groups": OrderedDict(),
            "todo_count": 0,
            "pg_total": 0,
        }
    )
    return context


def _assert_existing_todo_is_rendered(html: str, todo_id: int, title: str, description: str) -> None:
    assert '<section aria-label="할일 목록" aria-describedby="todo-list-status">' in html
    assert 'id="todo-list-status"' in html
    assert 'class="sr-only"' in html
    assert '<div id="todo-list-status" class="sr-only" role="status" aria-live="polite" aria-atomic="true">' in html
    assert "할일 목록 상태: 1개 항목이 있습니다." in html
    assert 'id="todoList"' in html
    assert f'id="todo-{todo_id}"' in html
    assert title in html
    assert description in html
    assert "mvp-render" in html
    assert "MVP" in html
    assert f'hx-get="/todos/{todo_id}/edit"' in html
    assert "업무가 없습니다" not in html


def _assert_todo_list_loading_state_contract(html: str) -> None:
    assert 'id="todoPage"' in html
    assert 'hx-indicator="#todo-list-loading"' in html
    assert 'id="todo-list-loading"' in html
    assert 'todo-list-loading htmx-indicator' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert 'aria-label="할일 목록 불러오는 중"' in html
    assert "할일 목록을 불러오는 중입니다" in html
    assert html.index('id="todo-list-loading"') < html.index('id="todoList"')


def _assert_todo_list_loading_css_contract(instance_name: str) -> None:
    app_css = (ROOT / instance_name / "static/css/app.css").read_text(encoding="utf-8")

    assert ".todo-list-loading.htmx-indicator" in app_css
    assert ".todo-list-loading.htmx-indicator.htmx-request" in app_css
    assert "display: none;" in app_css
    assert "display: block;" in app_css
    assert ".todo-list-loading.htmx-indicator.htmx-request::after" in app_css


def _assert_todo_creation_loading_css_contract(instance_name: str) -> None:
    app_css = (ROOT / instance_name / "static/css/app.css").read_text(encoding="utf-8")

    assert ".todo-create-loading.htmx-indicator" in app_css
    assert ".todo-create-loading.htmx-indicator.htmx-request" in app_css
    assert "display: none;" in app_css
    assert "display: block;" in app_css
    assert ".todo-create-loading.htmx-indicator.htmx-request::after" in app_css


def _assert_todo_edit_loading_css_contract(instance_name: str) -> None:
    app_css = (ROOT / instance_name / "static/css/app.css").read_text(encoding="utf-8")

    assert ".todo-edit-success" in app_css
    assert ".todo-edit-error" in app_css
    assert ".todo-edit-loading.htmx-indicator" in app_css
    assert ".todo-edit-loading.htmx-indicator.htmx-request" in app_css
    assert "background: var(--color-success-soft);" in app_css
    assert "background: var(--color-danger-soft);" in app_css
    assert "background: var(--color-info-soft);" in app_css
    assert "display: none;" in app_css
    assert "display: block;" in app_css
    assert ".todo-edit-loading.htmx-indicator.htmx-request::after" in app_css


def _assert_todo_save_feedback_focus_js_contract(instance_name: str) -> None:
    actions_js = (ROOT / instance_name / "static/js/actions.js").read_text(encoding="utf-8")

    assert "htmx:afterSwap" in actions_js
    assert "[data-todo-save-feedback]" in actions_js
    assert "scrollIntoView({block: 'nearest'})" in actions_js
    assert "focus({preventScroll: true})" in actions_js


def _assert_create_status_messages_are_screen_reader_named(html: str) -> None:
    assert 'id="todo-create-feedback"' in html
    assert 'id="todo-create-feedback" role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert 'aria-label="할일 추가 성공"' in html
    assert "할일이 추가되었습니다." in html

    assert 'id="todo-create-error"' in html
    assert 'id="todo-create-error" role="alert"' in html
    assert 'aria-live="assertive"' in html
    assert 'aria-label="할일 추가 오류"' in html
    assert "제목을 입력해주세요." in html


def _assert_update_status_message_is_screen_reader_named(html: str) -> None:
    assert 'class="todo-edit-success focus-accent mb-3 rounded-lg border px-3 py-2 text-sm font-medium"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert 'aria-label="할일 저장 성공"' in html
    assert 'tabindex="0"' in html
    assert 'data-todo-save-feedback' in html
    assert "변경사항이 저장되었습니다." in html


def _assert_edit_error_message_is_screen_reader_named(html: str, todo_id: int) -> None:
    assert f'id="todo-edit-error-{todo_id}"' in html
    assert 'class="todo-edit-error focus-accent rounded-lg border px-3 py-2 text-sm font-medium"' in html
    assert 'role="alert"' in html
    assert 'aria-live="assertive"' in html
    assert 'aria-atomic="true"' in html
    assert 'aria-label="할일 저장 오류"' in html
    assert 'tabindex="0"' in html
    assert 'data-todo-save-feedback' in html
    assert "제목을 입력해야 저장할 수 있습니다." in html


def _assert_todo_edit_form_initial_values(html: str, todo_id: int) -> None:
    html = unescape(html)

    assert f'id="editTodoForm-{todo_id}"' in html
    assert f'id="todo-edit-title-{todo_id}" type="text" name="title" value="Existing edit screen todo"' in html
    assert ">Existing description for the edit screen.</textarea>" in html
    assert 'name="due_date" aria-label="마감일" value="2026-06-30"' in html
    assert '<option value="3" selected>낮음</option>' in html
    assert '<option value="7" selected>MVP</option>' in html
    assert '<option value="custom" selected>사용자정의</option>' in html
    assert '<option value="3" selected>🔥 고에너지</option>' in html
    assert 'name="rrule_interval" aria-label="반복 간격" value="2"' in html
    assert '<option value="WEEKLY" selected>주</option>' in html
    assert 'value="MO" checked' in html
    assert 'value="WE" checked' in html
    assert '<option value="count" selected>횟수</option>' in html
    assert 'name="rrule_count" aria-label="반복 횟수" id="editRruleCount_' in html
    assert 'value="4" placeholder="횟수"' in html
    assert f'name="rrule_byday" id="editRruleByday_{todo_id}" value="MO,WE"' in html
    assert f'name="reminder_offsets" id="todoReminderOffsets_{todo_id}" value="[{chr(123)}"value":15,"unit":"minute"{chr(125)}]"' in html
    assert 'name="tags" aria-label="태그" value="mvp-render, edit-screen"' in html


def _assert_empty_todo_state_is_rendered(html: str) -> None:
    assert '<section aria-label="할일 목록" aria-describedby="todo-list-status">' in html
    assert 'id="todo-list-status"' in html
    assert '<div id="todo-list-status" class="sr-only" role="status" aria-live="polite" aria-atomic="true">' in html
    assert "할일 목록 상태: 0개 항목이 있습니다." in html
    assert 'id="todoList"' in html
    assert 'id="todo-empty-state"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert 'aria-labelledby="todo-empty-title"' in html
    assert 'aria-describedby="todo-empty-desc"' in html
    assert 'id="todo-empty-title"' in html
    assert 'id="todo-empty-desc"' in html
    assert "업무가 없습니다" in html
    assert "첫 할일을 추가해보세요" in html
    assert 'data-action="scroll-to-add-form"' in html
    assert 'data-form-id="addForm"' in html
    assert 'aria-label="새 할일 입력 폼으로 이동"' in html
    assert 'id="todo-4242"' not in html
    assert "unused empty title" not in html


def _assert_partial_empty_todo_state_is_rendered(html: str) -> None:
    assert 'id="todoList"' in html
    assert 'id="todo-empty-state"' in html
    assert 'class="empty-state"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert 'aria-labelledby="todo-empty-title"' in html
    assert 'aria-describedby="todo-empty-desc"' in html
    assert 'id="todo-empty-title"' in html
    assert 'id="todo-empty-desc"' in html
    assert 'aria-hidden="true"' in html
    assert "업무가 없습니다" in html
    assert "첫 할일을 추가해보세요" in html
    assert 'data-action="scroll-to-add-form"' in html
    assert 'data-form-id="addForm"' in html
    assert 'aria-label="새 할일 입력 폼으로 이동"' in html
    assert "할일 추가하기" in html
    assert 'id="todo-4242"' not in html


@pytest.mark.parametrize(("instance_name", "mod"), [("jm", jm_mod), ("my", my_mod)])
def test_core_todo_template_renders_supplied_existing_items(instance_name, mod):
    title = f"{instance_name.upper()} independent rendered todo {uuid4().hex}"
    description = f"{instance_name} existing item should be visible without route or DB access."
    todo_id = 9000 + len(instance_name)

    html = mod.templates.env.get_template("todos.html").render(
        _todo_context(title, description, todo_id)
    )

    _assert_existing_todo_is_rendered(html, todo_id, title, description)
    _assert_todo_list_loading_state_contract(html)


@pytest.mark.parametrize(("instance_name", "mod"), [("jm", jm_mod), ("my", my_mod)])
def test_core_todo_template_renders_independent_empty_state(instance_name, mod):
    html = mod.templates.env.get_template("todos.html").render(_empty_todo_context())

    _assert_empty_todo_state_is_rendered(html)
    _assert_todo_list_loading_state_contract(html)


@pytest.mark.parametrize(("instance_name", "mod"), [("jm", jm_mod), ("my", my_mod)])
def test_core_todo_partial_renders_empty_state_with_primary_action(instance_name, mod):
    html = mod.templates.env.get_template("partials/todo_list.html").render(
        {
            "todos": [],
            "priority_map": PRIORITY_MAP,
            "repeat_map": REPEAT_MAP,
            "today": date(2026, 6, 12),
        }
    )

    _assert_partial_empty_todo_state_is_rendered(html)


@pytest.mark.parametrize(("instance_name", "mod"), [("jm", jm_mod), ("my", my_mod)])
def test_core_todo_create_status_messages_have_screen_reader_contract(instance_name, mod):
    context = _empty_todo_context()
    context.update(
        {
            "todo_feedback": "할일이 추가되었습니다.",
            "todo_create_error": "제목을 입력해주세요.",
        }
    )

    html = mod.templates.env.get_template("todos.html").render(context)

    _assert_create_status_messages_are_screen_reader_named(html)


@pytest.mark.parametrize(("instance_name", "mod"), [("jm", jm_mod), ("my", my_mod)])
def test_core_todo_update_status_message_has_screen_reader_contract(instance_name, mod):
    context = _todo_context(
        f"{instance_name} saved status todo",
        "Rendered partial status message.",
        todo_id=5151,
    )
    todo = next(iter(context["todo_groups"].values()))[0]

    html = mod.templates.env.get_template("partials/todo_item.html").render(
        {
            **context,
            "todo": todo,
            "status_message": "변경사항이 저장되었습니다.",
        }
    )

    _assert_update_status_message_is_screen_reader_named(html)


@pytest.mark.parametrize(("instance_name", "mod"), [("jm", jm_mod), ("my", my_mod)])
def test_core_todo_edit_error_message_has_screen_reader_contract(instance_name, mod):
    context = _todo_context(
        f"{instance_name} edit error status todo",
        "Rendered edit error status message.",
        todo_id=6262,
    )
    todo = next(iter(context["todo_groups"].values()))[0]
    todo.update(
        {
            "category_id": None,
            "_rrule_interval": 1,
            "_rrule_freq": "DAILY",
            "_rrule_byday": [],
            "_rrule_bymonthday_str": "",
            "_rrule_count": None,
            "_rrule_until": None,
        }
    )

    html = mod.templates.env.get_template("partials/todo_edit_form.html").render(
        {
            **context,
            "todo": todo,
            "todo_edit_error": "제목을 입력해야 저장할 수 있습니다.",
        }
    )

    _assert_edit_error_message_is_screen_reader_named(html, todo["id"])


@pytest.mark.parametrize(("instance_name", "mod"), [("jm", jm_mod), ("my", my_mod)])
def test_core_todo_edit_form_renders_existing_values_as_initial_field_values(instance_name, mod):
    context = _todo_context(
        "Existing edit screen todo",
        "Existing description for the edit screen.",
        todo_id=7373,
    )
    todo = next(iter(context["todo_groups"].values()))[0]
    todo.update(
        {
            "category_id": 7,
            "due_date": "2026-06-30",
            "priority": 3,
            "repeat_type": "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=4",
            "energy_level": 3,
            "reminder_offsets": '[{"value":15,"unit":"minute"}]',
            "tags": '["mvp-render", "edit-screen"]',
            "_rrule_interval": 2,
            "_rrule_freq": "WEEKLY",
            "_rrule_byday": ["MO", "WE"],
            "_rrule_bymonthday_str": "",
            "_rrule_count": 4,
            "_rrule_until": "",
        }
    )

    html = mod.templates.env.get_template("partials/todo_edit_form.html").render(
        {
            **context,
            "todo": todo,
            "todo_edit_error": "",
        }
    )

    _assert_todo_edit_form_initial_values(html, todo["id"])


@pytest.mark.parametrize("instance_name", ["jm", "my"])
def test_core_todo_list_loading_indicator_has_visible_htmx_request_css(instance_name):
    _assert_todo_list_loading_css_contract(instance_name)


@pytest.mark.parametrize("instance_name", ["jm", "my"])
def test_core_todo_creation_loading_indicator_has_visible_htmx_request_css(instance_name):
    _assert_todo_creation_loading_css_contract(instance_name)


@pytest.mark.parametrize("instance_name", ["jm", "my"])
def test_core_todo_edit_loading_indicator_has_visible_htmx_request_css(instance_name):
    _assert_todo_edit_loading_css_contract(instance_name)


@pytest.mark.parametrize("instance_name", ["jm", "my"])
def test_core_todo_save_feedback_moves_keyboard_focus_after_htmx_swap(instance_name):
    _assert_todo_save_feedback_focus_js_contract(instance_name)
