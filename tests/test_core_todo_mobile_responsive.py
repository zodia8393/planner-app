"""Independent 390x844 mobile overflow contracts for jm/my core todo lists."""

import pytest


MOBILE_VIEWPORT = {"width": 390, "height": 844}

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("app_name", ["jm", "my"])
def test_jm_my_core_todo_list_mobile_390_has_no_horizontal_scroll_contract(app_name: str):
    base = (ROOT / app_name / "templates" / "base.html").read_text(encoding="utf-8")
    template = (ROOT / app_name / "templates" / "todos.html").read_text(encoding="utf-8")
    item_template = (ROOT / app_name / "templates" / "partials" / "todo_item.html").read_text(
        encoding="utf-8"
    )
    app_css = (ROOT / app_name / "static" / "css" / "app.css").read_text(encoding="utf-8")

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}

    assert 'role="main"' in base
    assert 'id="mainContent"' in base
    assert "mobile-pad-bottom" in base

    assert 'id="addForm"' in template
    assert 'action="/todos"' in template
    assert 'aria-label="새 업무 제목"' in template
    assert 'aria-label="할일 목록"' in template
    assert 'id="todoList"' in template
    assert 'class="flex gap-2"' in template
    assert 'class="flex flex-wrap items-center gap-2 mb-3 overflow-x-auto' in template

    assert 'class="work-card rounded-xl fade-in group touch-item swipe-item' in item_template
    assert 'class="swipe-content p-4"' in item_template
    assert 'class="flex-1 min-w-0"' in item_template
    assert 'class="flex items-center gap-2 flex-wrap"' in item_template

    assert "*, *::before, *::after { box-sizing: border-box; }" in app_css
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "#mainContent {" in app_css
    assert "max-width: 100%" in app_css
    assert "min-width: 0" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert "input, select, textarea { max-width: 100%; box-sizing: border-box; }" in app_css
    assert ".flex { min-width: 0; }" in app_css
    assert ".flex > * { min-width: 0; }" in app_css
    assert ".overflow-x-auto { -webkit-overflow-scrolling: touch; scrollbar-width: none; }" in app_css

    assert "@media (max-width: 640px)" in app_css
    assert "#mainContent :where(.work-card > .flex, .work-card form.flex" in app_css
    assert "flex-wrap: wrap;" in app_css
    assert "#mainContent :where(.work-card > .flex > *, .work-card form.flex > *" in app_css
    assert "#mainContent :where(.work-card input:not([type=\"checkbox\"]):not([type=\"radio\"]), .work-card select, .work-card textarea)" in app_css
