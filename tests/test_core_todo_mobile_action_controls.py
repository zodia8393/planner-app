"""Independent 390x844 mobile touch containment contracts for jm/my todo actions."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MOBILE_VIEWPORT = {"width": 390, "height": 844}
MIN_TOUCH_TARGET_REM = "2.75rem"


@pytest.mark.parametrize("app_name", ["jm", "my"])
def test_jm_my_core_todo_mobile_390_action_controls_are_touch_sized_and_contained(
    app_name: str,
):
    template = (ROOT / app_name / "templates" / "todos.html").read_text(encoding="utf-8")
    item_template = (
        ROOT / app_name / "templates" / "partials" / "todo_item.html"
    ).read_text(encoding="utf-8")
    app_css = (ROOT / app_name / "static" / "css" / "app.css").read_text(
        encoding="utf-8"
    )

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}

    # Core list top-level buttons must be wrap-safe within the selected /todos screen.
    assert 'id="todoPage"' in template
    assert 'class="flex items-center gap-2 mb-3"' in template
    assert 'class="flex flex-wrap items-center gap-2 mb-3 overflow-x-auto' in template
    assert 'id="bulkToggle"' in template
    assert 'id="bulkBar"' in template
    assert 'class="hidden mb-3 p-3 rounded-xl flex flex-wrap items-center gap-2 text-sm"' in template
    assert 'class="flex-1 min-w-0"' in template
    assert 'aria-label="전체 선택"' in template
    assert 'aria-label="선택 항목 완료 처리"' in template
    assert 'aria-label="선택 항목 삭제"' in template
    assert 'aria-label="일괄 처리 취소"' in template

    # Per-item action controls must have explicit hooks for mobile touch sizing.
    assert 'class="todo-complete-toggle flex-shrink-0 mt-0.5 w-5 h-5 rounded border-2' in item_template
    assert 'class="todo-action-bar flex items-center gap-1 flex-shrink-0' in item_template
    assert item_template.count('class="todo-action-btn p-2 rounded') == 3
    assert 'aria-label="하위 작업"' in item_template
    assert 'aria-label="편집"' in item_template
    assert 'aria-label="삭제"' in item_template

    # 390px mobile CSS contract: no page escape, no unwrapped action bar,
    # and all main buttons/action controls are at least 44px touch targets.
    assert "@media (max-width: 640px)" in app_css
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "#mainContent :where(button, a, .btn-accent" in app_css
    assert "#todoPage :where(.btn-sm, .btn-accent, .todo-action-btn, .todo-complete-toggle)" in app_css
    assert f"min-height: {MIN_TOUCH_TARGET_REM};" in app_css
    assert "#todoPage :where(.todo-action-btn, .todo-complete-toggle)" in app_css
    assert f"min-width: {MIN_TOUCH_TARGET_REM};" in app_css
    assert "#todoPage .todo-action-bar" in app_css
    assert "justify-content: flex-end;" in app_css
    assert "#bulkBar {" in app_css
    assert "flex-wrap: wrap;" in app_css
    assert "#bulkBar .flex-1" in app_css
    assert "flex-basis: 100%;" in app_css
