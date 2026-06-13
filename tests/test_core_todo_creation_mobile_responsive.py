"""Independent 390x844 mobile containment contracts for jm/my todo creation."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MOBILE_VIEWPORT = {"width": 390, "height": 844}


def _add_form_markup(template: str) -> str:
    start = template.index('id="addForm"')
    end = template.index("<!-- Bulk action bar -->")
    return template[start:end]


@pytest.mark.parametrize("app_name", ["jm", "my"])
def test_jm_my_todo_creation_mobile_390_has_no_document_or_container_overflow_contract(
    app_name: str,
):
    base = (ROOT / app_name / "templates" / "base.html").read_text(encoding="utf-8")
    template = (ROOT / app_name / "templates" / "todos.html").read_text(encoding="utf-8")
    app_css = (ROOT / app_name / "static" / "css" / "app.css").read_text(encoding="utf-8")
    add_form = _add_form_markup(template)

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}

    # Document and primary page containers must clip accidental horizontal overflow.
    assert 'role="main"' in base
    assert 'id="mainContent"' in base
    assert "mobile-pad-bottom" in base
    assert "*, *::before, *::after { box-sizing: border-box; }" in app_css
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "#mainContent {" in app_css
    assert "max-width: 100%" in app_css
    assert "min-width: 0" in app_css
    assert "overflow-wrap: anywhere" in app_css

    # The selected MVP creation surface is the /todos add form, not a separate page.
    assert 'id="todoPage"' in template
    assert 'id="addForm"' in template
    assert 'class="work-card rounded-xl p-4 mb-4" id="addForm"' in template
    assert '<form id="addTodoForm" action="/todos" method="POST" hx-post="/todos" hx-indicator="#todo-create-loading">' in add_form
    assert 'aria-label="새 업무 제목"' in add_form
    assert 'type="submit"' in add_form
    assert 'aria-describedby="todo-create-loading"' in add_form
    assert 'id="todo-create-loading"' in add_form
    assert 'todo-create-loading htmx-indicator' in add_form
    assert 'role="status"' in add_form
    assert 'aria-live="polite"' in add_form
    assert "할일을 추가하는 중입니다" in add_form
    assert "추가" in add_form

    # Creation controls must stay bounded by the form/card on 390px mobile.
    assert 'class="input-premium flex-1 px-3.5 py-2.5 text-sm"' in add_form
    assert 'class="flex flex-wrap items-center gap-1.5"' in add_form
    assert 'class="px-2 py-1.5 text-xs border rounded-lg focus-accent flex-1 min-w-24"' in add_form
    assert 'class="flex gap-1.5"' in add_form
    assert 'id="newTodoOffsetSel"' in add_form
    assert 'class="flex-1 px-2 py-1.5 text-xs border rounded-lg focus-accent"' in add_form
    assert 'id="addRrulePanel"' in add_form
    assert 'class="w-full mt-2 px-3 py-2 text-sm border rounded-lg focus-accent hidden"' in add_form

    assert "#mainContent :where(.work-card, details, section, article, form, table)" in app_css
    assert "#mainContent :where(button, a, .btn-accent" in app_css
    assert "input, select, textarea { max-width: 100%; box-sizing: border-box; }" in app_css
    assert "form { max-width: 100%; }" in app_css
    assert ".flex { min-width: 0; }" in app_css
    assert ".flex > * { min-width: 0; }" in app_css

    assert "@media (max-width: 640px)" in app_css
    assert "#mainContent :where(.work-card > .flex, .work-card form.flex" in app_css
    assert "flex-wrap: wrap;" in app_css
    assert "#mainContent :where(.work-card > .flex > *, .work-card form.flex > *" in app_css
    assert "#mainContent :where(.work-card input:not([type=\"checkbox\"]):not([type=\"radio\"]), .work-card select, .work-card textarea)" in app_css
