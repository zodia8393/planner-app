"""MVP dashboard and core-list input labeling checks.

The jm/my apps are imported with isolated temp databases via conftest.py, so
these checks do not touch production planner data.
"""

from html.parser import HTMLParser
from collections import OrderedDict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from common.constants import PRIORITY_MAP, REPEAT_MAP, RRULE_DAY_OPTIONS, RRULE_FREQ_OPTIONS
from conftest import jm_app, jm_mod, my_app, my_mod


ORIGIN = {"origin": "http://testserver", "host": "testserver"}


class InputLabelParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.controls: list[dict] = []
        self.label_targets: set[str] = set()
        self._label_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        raw = self.get_starttag_text() or ""

        if tag == "label":
            if attr.get("for"):
                self.label_targets.add(attr["for"])
            self._label_depth += 1

        if tag in {"input", "select", "textarea"}:
            self.controls.append(
                {
                    "tag": tag,
                    "attrs": attr,
                    "wrapped_by_label": self._label_depth > 0,
                    "html": raw,
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_depth:
            self._label_depth -= 1


class AddFormInputLabelParser(InputLabelParser):
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self._add_form_depth = 0
        self._in_add_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        entered_add_form = False

        if tag == "div" and attr.get("id") == "addForm":
            self._in_add_form = True
            self._add_form_depth = 1
            entered_add_form = True
        elif self._in_add_form and tag not in self._VOID_TAGS:
            self._add_form_depth += 1

        if self._in_add_form:
            super().handle_starttag(tag, attrs)

        if entered_add_form and tag in self._VOID_TAGS:
            self._in_add_form = False
            self._add_form_depth = 0

    def handle_endtag(self, tag: str) -> None:
        if self._in_add_form:
            super().handle_endtag(tag)
            self._add_form_depth -= 1
            if self._add_form_depth <= 0:
                self._in_add_form = False


class EditFormInputLabelParser(InputLabelParser):
    _VOID_TAGS = AddFormInputLabelParser._VOID_TAGS

    def __init__(self, form_id: str) -> None:
        super().__init__()
        self.form_id = form_id
        self._edit_form_depth = 0
        self._in_edit_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        entered_edit_form = False

        if tag == "form" and attr.get("id") == self.form_id:
            self._in_edit_form = True
            self._edit_form_depth = 1
            entered_edit_form = True
        elif self._in_edit_form and tag not in self._VOID_TAGS:
            self._edit_form_depth += 1

        if self._in_edit_form:
            super().handle_starttag(tag, attrs)

        if entered_edit_form and tag in self._VOID_TAGS:
            self._in_edit_form = False
            self._edit_form_depth = 0

    def handle_endtag(self, tag: str) -> None:
        if self._in_edit_form:
            super().handle_endtag(tag)
            self._edit_form_depth -= 1
            if self._edit_form_depth <= 0:
                self._in_edit_form = False


def _is_hidden_control(control: dict) -> bool:
    attrs = control["attrs"]
    if control["tag"] == "input" and attrs.get("type", "text").lower() == "hidden":
        return True
    if attrs.get("aria-hidden") == "true":
        return True
    classes = set(attrs.get("class", "").split())
    return bool({"hidden", "sr-only"} & classes)


def _has_explicit_label(control: dict, parser: InputLabelParser) -> bool:
    attrs = control["attrs"]
    return bool(
        attrs.get("aria-label", "").strip()
        or attrs.get("aria-labelledby", "").strip()
        or (attrs.get("id") and attrs["id"] in parser.label_targets)
        or control["wrapped_by_label"]
    )


def _control_summary(control: dict) -> dict[str, str]:
    attrs = control["attrs"]
    return {
        "tag": control["tag"],
        "type": attrs.get("type", ""),
        "id": attrs.get("id", ""),
        "name": attrs.get("name", ""),
        "placeholder": attrs.get("placeholder", ""),
        "html": control["html"][:180].replace("\n", " "),
    }


def _assert_inputs_have_labels(app_name: str, route: str, html: str, *, include_hidden: bool = False) -> None:
    parser = InputLabelParser()
    parser.feed(html)

    offenders = [
        _control_summary(control)
        for control in parser.controls
        if (include_hidden or not _is_hidden_control(control)) and not _has_explicit_label(control, parser)
    ]

    assert not offenders, f"{app_name} {route}: input controls without labels: {offenders}"


def _assert_add_form_inputs_have_labels(app_name: str, html: str) -> None:
    parser = AddFormInputLabelParser()
    parser.feed(html)

    assert parser.controls, f"{app_name} /todos: add form controls were not found"

    offenders = [
        _control_summary(control)
        for control in parser.controls
        if not _has_explicit_label(control, parser)
    ]

    assert not offenders, f"{app_name} /todos add form: input controls without labels: {offenders}"


def _has_visible_focus_treatment(control: dict) -> bool:
    classes = set(control["attrs"].get("class", "").split())
    return bool({"focus-accent", "input-premium"} & classes)


def _assert_add_form_inputs_have_visible_focus_treatment(app_name: str, html: str) -> None:
    parser = AddFormInputLabelParser()
    parser.feed(html)

    assert parser.controls, f"{app_name} /todos: add form controls were not found"

    offenders = [
        _control_summary(control)
        for control in parser.controls
        if not _is_hidden_control(control) and not _has_visible_focus_treatment(control)
    ]

    assert not offenders, f"{app_name} /todos add form: controls without visible focus treatment: {offenders}"


def _todo_creation_form_context() -> dict:
    return {
        "is_htmx": True,
        "page": "todos",
        "todo_groups": OrderedDict(),
        "todo_count": 0,
        "categories": [{"id": 1, "name": "MVP", "color": "#2563eb"}],
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
        "pg_total": 0,
        "pg_total_pages": 1,
        "pg_has_next": False,
        "pg_has_prev": False,
        "pg_filter_qs": "",
        "today": date(2026, 6, 12),
        "config": {"planner_name": "Test Planner"},
    }


def _todo_edit_form_context() -> dict:
    return {
        "todo": SimpleNamespace(
            id=123,
            title="Existing accessible label unit todo",
            description="Rendered directly for edit form input labeling.",
            due_date="2026-06-12",
            priority=2,
            category_id=1,
            repeat_type="FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=6",
            energy_level=2,
            tags='["mvp-input-a11y", "edit"]',
            reminder_offsets='[{"value":10,"unit":"minute"}]',
            subtasks=[],
            _rrule_interval=2,
            _rrule_freq="WEEKLY",
            _rrule_byday=["MO", "WE"],
            _rrule_bymonthday_str="",
            _rrule_count=6,
            _rrule_until="",
        ),
        "categories": [{"id": 1, "name": "MVP", "color": "#2563eb"}],
        "priority_map": PRIORITY_MAP,
        "repeat_map": REPEAT_MAP,
        "rrule_day_options": RRULE_DAY_OPTIONS,
        "rrule_to_korean": lambda value: "매 2주 월, 수 6회",
        "todo_edit_error": "",
    }


async def _setup_my_profile(client: httpx.AsyncClient) -> int:
    profile_name = f"InputA11y{uuid4().hex[:8]}"
    response = await client.post(
        "/setup",
        data={"name": profile_name},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303

    with my_mod.get_db() as conn:
        row = conn.execute("SELECT id FROM profiles WHERE name=?", (profile_name,)).fetchone()
    assert row is not None
    return int(row["id"])


def _insert_existing_todo(mod, profile_id: int, title: str) -> int:
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
            (
                profile_id,
                title,
                "Temporary isolated edit-label check todo.",
                2,
                "2026-06-12",
                '["mvp-input-a11y"]',
                max_order + 1,
            ),
        )
        return int(cur.lastrowid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app_name,app",
    [
        ("jm", jm_app),
        ("my", my_app),
    ],
)
async def test_jm_my_mvp_dashboard_and_core_list_inputs_have_labels(app_name, app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        if app_name == "my":
            await _setup_my_profile(client)

        for route in ("/", "/todos"):
            response = await client.get(route)
            assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
            _assert_inputs_have_labels(app_name, route, response.text)
            if route == "/todos":
                _assert_add_form_inputs_have_labels(app_name, response.text)


@pytest.mark.parametrize(
    "app_name,mod",
    [
        ("jm", jm_mod),
        ("my", my_mod),
    ],
)
def test_jm_my_todo_creation_form_inputs_have_accessible_names_unit(app_name, mod):
    html = mod.templates.env.get_template("todos.html").render(_todo_creation_form_context())
    parser = AddFormInputLabelParser()
    parser.feed(html)

    expected_named_controls = {
        "title",
        "due_date",
        "priority",
        "category_id",
        "repeat_type",
        "energy_level",
        "tags",
        "reminder_offsets",
        "rrule_interval",
        "rrule_freq",
        "rrule_bymonthday",
        "rrule_end_type",
        "rrule_count",
        "rrule_until",
        "rrule_byday",
        "description",
    }
    actual_named_controls = {
        control["attrs"].get("name", "")
        for control in parser.controls
        if control["attrs"].get("name")
    }

    assert expected_named_controls <= actual_named_controls, (
        f"{app_name} /todos add form: expected creation controls were not rendered: "
        f"{sorted(expected_named_controls - actual_named_controls)}"
    )
    _assert_add_form_inputs_have_labels(app_name, html)


@pytest.mark.parametrize(
    "app_name,mod",
    [
        ("jm", jm_mod),
        ("my", my_mod),
    ],
)
def test_jm_my_todo_creation_initial_render_shows_readable_labels_help_and_actions(app_name, mod):
    html = mod.templates.env.get_template("todos.html").render(_todo_creation_form_context())

    assert 'id="addForm"' in html
    assert 'for="newTodoTitle" id="newTodoTitleLabel"' in html
    assert 'style="color: var(--color-text);">새 업무 제목</label>' in html
    assert 'id="newTodoHelp"' in html
    assert "제목을 입력한 뒤 추가를 누르세요." in html
    assert "마감일, 우선순위, 반복, 태그" in html
    assert 'placeholder="할 일 입력 (/오늘, /높음 등 슬래시 명령 지원)"' in html
    assert 'aria-describedby="newTodoHelp todo-create-validation"' in html
    assert 'class="todo-create-submit btn-accent px-5 py-2.5 rounded-lg text-sm"' in html
    assert "추가" in html
    assert 'aria-label="할일 추가 취소"' in html
    assert "취소" in html

    app_css = (Path(__file__).resolve().parents[1] / app_name / "static" / "css" / "app.css").read_text(
        encoding="utf-8"
    )
    assert "--color-text: #1c1917;" in app_css
    assert "--color-text-muted: #57534e;" in app_css
    assert "::placeholder { color: #78716c !important; }" in app_css
    assert ".btn-accent" in app_css


@pytest.mark.parametrize(
    "app_name,mod",
    [
        ("jm", jm_mod),
        ("my", my_mod),
    ],
)
def test_jm_my_todo_edit_form_inputs_have_accessible_names_unit(app_name, mod):
    html = mod.templates.env.get_template("partials/todo_edit_form.html").render(_todo_edit_form_context())
    parser = EditFormInputLabelParser("editTodoForm-123")
    parser.feed(html)

    assert parser.controls, f"{app_name} edit todo form: controls were not found"

    expected_named_controls = {
        "title",
        "description",
        "due_date",
        "priority",
        "category_id",
        "repeat_type",
        "energy_level",
        "rrule_interval",
        "rrule_freq",
        "rrule_bymonthday",
        "rrule_end_type",
        "rrule_count",
        "rrule_until",
        "rrule_byday",
        "reminder_offsets",
        "tags",
    }
    actual_named_controls = {
        control["attrs"].get("name", "")
        for control in parser.controls
        if control["attrs"].get("name")
    }

    assert expected_named_controls <= actual_named_controls, (
        f"{app_name} edit todo form: expected edit controls were not rendered: "
        f"{sorted(expected_named_controls - actual_named_controls)}"
    )

    offenders = [
        _control_summary(control)
        for control in parser.controls
        if not _has_explicit_label(control, parser)
    ]

    assert not offenders, f"{app_name} edit todo form: input controls without labels: {offenders}"


@pytest.mark.parametrize(
    "app_name,mod",
    [
        ("jm", jm_mod),
        ("my", my_mod),
    ],
)
def test_jm_my_todo_edit_form_inputs_have_visible_focus_treatment_unit(app_name, mod):
    html = mod.templates.env.get_template("partials/todo_edit_form.html").render(_todo_edit_form_context())
    parser = EditFormInputLabelParser("editTodoForm-123")
    parser.feed(html)

    assert parser.controls, f"{app_name} edit todo form: controls were not found"

    offenders = [
        _control_summary(control)
        for control in parser.controls
        if not _is_hidden_control(control) and not _has_visible_focus_treatment(control)
    ]

    assert not offenders, f"{app_name} edit todo form: controls without visible focus treatment: {offenders}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app_name,app,mod,default_profile_id",
    [
        ("jm", jm_app, jm_mod, 1),
        ("my", my_app, my_mod, None),
    ],
)
async def test_jm_my_core_todo_edit_save_form_inputs_have_labels(app_name, app, mod, default_profile_id):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = default_profile_id
        if app_name == "my":
            profile_id = await _setup_my_profile(client)

        todo_id = _insert_existing_todo(mod, profile_id, f"{app_name} edit labels {uuid4().hex}")
        response = await client.get(
            f"/todos/{todo_id}/edit",
            headers={**ORIGIN, "HX-Request": "true"},
        )

    assert response.status_code == 200, f"{app_name} edit form: status {response.status_code}"
    _assert_inputs_have_labels(app_name, f"/todos/{todo_id}/edit", response.text, include_hidden=True)
