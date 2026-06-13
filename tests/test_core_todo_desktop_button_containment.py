"""
1440x900 desktop button containment checks for jm/my MVP core todo screens.

The apps come from conftest.py with isolated temp databases, so this test does
not touch production data.
"""

import asyncio

import pytest

from conftest import run_async, jm_app, jm_mod, my_app, my_mod
from test_core_todo_desktop_responsive import (
    DESKTOP_VIEWPORT,
    _assert_static_desktop_containment_contract,
    _assert_static_desktop_edit_containment_contract,
    _fetch_core_todo_edit_screen_html,
    _fetch_core_todo_html,
    _inline_render_css,
    optional_chromium_browser,
)


def _desktop_button_containment_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const selectors = [
                ['listView', 'a[href="/todos"]', '#todoPage'],
                ['kanbanView', 'a[href="/todos/kanban"]', '#todoPage'],
                ['filterAll', 'a[href^="/todos?filter=all"]', '#todoPage'],
                ['filterActive', 'a[href^="/todos?filter=active"]', '#todoPage'],
                ['filterCompleted', 'a[href^="/todos?filter=completed"]', '#todoPage'],
                ['bulkToggle', '#bulkToggle', '#todoPage'],
                ['addSubmit', '#addForm button[type="submit"]', '#addForm'],
                ['addDescriptionToggle', '#addForm [data-action="toggle-desc-field"]', '#addForm'],
                ['addReminder', '#addForm [data-action="add-new-todo-offset"]', '#addForm'],
            ];
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number.parseFloat(style.opacity || '1') > 0.01
                    && rect.width > 1
                    && rect.height > 1;
            };
            const labelFor = (el) => (el.getAttribute('aria-label') || el.innerText || el.textContent || '')
                .replace(/\\s+/g, ' ')
                .trim();
            const checks = selectors.map(([name, selector, containerSelector]) => {
                const container = document.querySelector(containerSelector);
                const el = container ? container.querySelector(selector) : null;
                if (!el || !container) {
                    return { name, selector, containerSelector, missing: true };
                }
                const rect = el.getBoundingClientRect();
                const containerRect = container.getBoundingClientRect();
                return {
                    name,
                    selector,
                    containerSelector,
                    label: labelFor(el),
                    visible: visible(el),
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    top: Math.round(rect.top),
                    bottom: Math.round(rect.bottom),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    containerLeft: Math.round(containerRect.left),
                    containerRight: Math.round(containerRect.right),
                    containerTop: Math.round(containerRect.top),
                    containerBottom: Math.round(containerRect.bottom),
                    clippedByViewport: rect.left < -2 || rect.right > viewportWidth + 2,
                    outsideContainer:
                        rect.left < containerRect.left - 2
                        || rect.right > containerRect.right + 2
                        || rect.top < containerRect.top - 2
                        || rect.bottom > containerRect.bottom + 2,
                };
            });
            return {
                viewportWidth,
                checkedCount: checks.length,
                failures: checks.filter((item) =>
                    item.missing
                    || !item.visible
                    || item.width < 24
                    || item.height < 24
                    || item.clippedByViewport
                    || item.outsideContainer
                ),
                checks,
            };
        }"""
    )


def _desktop_creation_button_containment_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const selectors = [
                ['titleInput', '#newTodoTitle', '#addForm'],
                ['submit', '#addForm button[type="submit"]', '#addForm'],
                ['cancel', '#addForm button[type="reset"]', '#addForm'],
                ['optionsSummary', '#addFormOptions > summary', '#addForm'],
                ['dueDate', '#addForm input[name="due_date"]', '#addForm'],
                ['priority', '#addForm select[name="priority"]', '#addForm'],
                ['category', '#addForm select[name="category_id"]', '#addForm'],
                ['repeatType', '#addForm select[name="repeat_type"]', '#addForm'],
                ['energyLevel', '#addForm select[name="energy_level"]', '#addForm'],
                ['tags', '#addForm input[name="tags"]', '#addForm'],
                ['descriptionToggle', '#addForm [data-action="toggle-desc-field"]', '#addForm'],
                ['reminderSelect', '#newTodoOffsetSel', '#addForm'],
                ['reminderAdd', '#addForm [data-action="add-new-todo-offset"]', '#addForm'],
            ];
            const form = document.querySelector('#addForm');
            const formRect = form?.getBoundingClientRect();
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number.parseFloat(style.opacity || '1') > 0.01
                    && rect.width > 1
                    && rect.height > 1;
            };
            const labelFor = (el) => (el.getAttribute('aria-label') || el.innerText || el.textContent || '')
                .replace(/\\s+/g, ' ')
                .trim();
            const checks = selectors.map(([name, selector, containerSelector]) => {
                const container = document.querySelector(containerSelector);
                const el = container ? container.querySelector(selector) : null;
                if (!el || !container) {
                    return { name, selector, containerSelector, missing: true };
                }
                const rect = el.getBoundingClientRect();
                const containerRect = container.getBoundingClientRect();
                return {
                    name,
                    selector,
                    containerSelector,
                    label: labelFor(el),
                    visible: visible(el),
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    top: Math.round(rect.top),
                    bottom: Math.round(rect.bottom),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    containerLeft: Math.round(containerRect.left),
                    containerRight: Math.round(containerRect.right),
                    containerTop: Math.round(containerRect.top),
                    containerBottom: Math.round(containerRect.bottom),
                    clippedByViewport: rect.left < -2 || rect.right > viewportWidth + 2,
                    outsideContainer:
                        rect.left < containerRect.left - 2
                        || rect.right > containerRect.right + 2
                        || rect.top < containerRect.top - 2
                        || rect.bottom > containerRect.bottom + 2,
                };
            });
            return {
                viewportWidth,
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                form: form && formRect ? {
                    left: Math.round(formRect.left),
                    right: Math.round(formRect.right),
                    width: Math.round(formRect.width),
                    scrollWidth: form.scrollWidth,
                    clientWidth: form.clientWidth,
                    hasHorizontalScroll: form.scrollWidth > form.clientWidth + 2,
                } : null,
                checkedCount: checks.length,
                failures: checks.filter((item) =>
                    item.missing
                    || !item.visible
                    || item.width < 24
                    || item.height < 24
                    || item.clippedByViewport
                    || item.outsideContainer
                ),
                checks,
            };
        }"""
    )


def _desktop_edit_button_containment_metrics(page, todo_id: int):
    return page.evaluate(
        """(todoId) => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const containerSelector = `#todo-${todoId}`;
            const selectors = [
                ['topCancel', `[data-action="cancel-edit"]`, containerSelector],
                ['editTitle', `#editTodoForm-${todoId} input[name="title"]`, containerSelector],
                ['description', `#editTodoForm-${todoId} textarea[name="description"]`, containerSelector],
                ['dueDate', `#editTodoForm-${todoId} input[name="due_date"]`, containerSelector],
                ['priority', `#editTodoForm-${todoId} select[name="priority"]`, containerSelector],
                ['category', `#editTodoForm-${todoId} select[name="category_id"]`, containerSelector],
                ['repeatType', `#editTodoForm-${todoId} select[name="repeat_type"]`, containerSelector],
                ['energyLevel', `#editTodoForm-${todoId} select[name="energy_level"]`, containerSelector],
                ['reminderSelect', `#todoOffsetSel_${todoId}`, containerSelector],
                ['reminderAdd', `[data-action="add-edit-todo-offset"]`, containerSelector],
                ['tags', `#editTodoForm-${todoId} input[name="tags"]`, containerSelector],
                ['subtaskTitle', `form[hx-post="/todos/${todoId}/subtasks"] input[name="title"]`, containerSelector],
                ['subtaskAdd', `form[hx-post="/todos/${todoId}/subtasks"] button[type="submit"]`, containerSelector],
                ['bottomCancel', `.todo-edit-actions [data-action="cancel-edit"]`, containerSelector],
                ['save', `button[form="editTodoForm-${todoId}"][type="submit"]`, containerSelector],
                ['delete', `button[data-action="delete-todo"]`, containerSelector],
            ];
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number.parseFloat(style.opacity || '1') > 0.01
                    && rect.width > 1
                    && rect.height > 1;
            };
            const labelFor = (el) => (el.getAttribute('aria-label') || el.value || el.innerText || el.textContent || '')
                .replace(/\\s+/g, ' ')
                .trim();
            const rectSummary = (selector) => {
                const el = document.querySelector(selector);
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    selector,
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    top: Math.round(rect.top),
                    bottom: Math.round(rect.bottom),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    hasHorizontalScroll: el.scrollWidth > el.clientWidth + 2,
                    clippedByViewport: rect.left < -2 || rect.right > viewportWidth + 2,
                };
            };
            const checks = selectors.map(([name, selector, parentSelector]) => {
                const container = document.querySelector(parentSelector);
                const el = container ? container.querySelector(selector) : null;
                if (!el || !container) {
                    return { name, selector, parentSelector, missing: true };
                }
                const rect = el.getBoundingClientRect();
                const containerRect = container.getBoundingClientRect();
                return {
                    name,
                    selector,
                    parentSelector,
                    label: labelFor(el),
                    visible: visible(el),
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    top: Math.round(rect.top),
                    bottom: Math.round(rect.bottom),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    containerLeft: Math.round(containerRect.left),
                    containerRight: Math.round(containerRect.right),
                    containerTop: Math.round(containerRect.top),
                    containerBottom: Math.round(containerRect.bottom),
                    clippedByViewport: rect.left < -2 || rect.right > viewportWidth + 2,
                    outsideContainer:
                        rect.left < containerRect.left - 2
                        || rect.right > containerRect.right + 2
                        || rect.top < containerRect.top - 2
                        || rect.bottom > containerRect.bottom + 2,
                };
            });
            return {
                viewportWidth,
                viewportHeight: window.innerHeight,
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                containers: {
                    card: rectSummary(containerSelector),
                    form: rectSummary(`#editTodoForm-${todoId}`),
                    actionRow: rectSummary(`#todo-${todoId} .todo-edit-actions`),
                },
                checkedCount: checks.length,
                failures: checks.filter((item) =>
                    item.missing
                    || !item.visible
                    || item.clippedByViewport
                    || item.outsideContainer
                ),
                checks,
            };
        }""",
        todo_id,
    )


def _desktop_list_item_action_containment_metrics(page, todo_id: int):
    return page.evaluate(
        """(todoId) => {
            const viewportWidth = window.innerWidth;
            const containerSelector = `#todo-${todoId}`;
            const selectors = [
                ['complete', '.todo-complete-toggle', containerSelector],
                ['subtask', '[data-action="toggle-subtask-form"]', containerSelector],
                ['edit', '[hx-get$="/edit"]', containerSelector],
                ['delete', 'button[hx-delete]', containerSelector],
            ];
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number.parseFloat(style.opacity || '1') > 0.01
                    && rect.width > 1
                    && rect.height > 1;
            };
            const labelFor = (el) => (el.getAttribute('aria-label') || el.innerText || el.textContent || '')
                .replace(/\\s+/g, ' ')
                .trim();
            const checks = selectors.map(([name, selector, parentSelector]) => {
                const container = document.querySelector(parentSelector);
                const el = container ? container.querySelector(selector) : null;
                if (!el || !container) {
                    return { name, selector, parentSelector, missing: true };
                }
                const rect = el.getBoundingClientRect();
                const containerRect = container.getBoundingClientRect();
                return {
                    name,
                    selector,
                    parentSelector,
                    label: labelFor(el),
                    visible: visible(el),
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    top: Math.round(rect.top),
                    bottom: Math.round(rect.bottom),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    containerLeft: Math.round(containerRect.left),
                    containerRight: Math.round(containerRect.right),
                    containerTop: Math.round(containerRect.top),
                    containerBottom: Math.round(containerRect.bottom),
                    clippedByViewport: rect.left < -2 || rect.right > viewportWidth + 2,
                    outsideContainer:
                        rect.left < containerRect.left - 2
                        || rect.right > containerRect.right + 2
                        || rect.top < containerRect.top - 2
                        || rect.bottom > containerRect.bottom + 2,
                };
            });
            return {
                viewportWidth,
                checkedCount: checks.length,
                failures: checks.filter((item) =>
                    item.missing
                    || !item.visible
                    || item.width < 20
                    || item.height < 20
                    || item.clippedByViewport
                    || item.outsideContainer
                ),
                checks,
            };
        }""",
        todo_id,
    )


@pytest.mark.parametrize("app_name,app", [("jm", jm_app), ("my", my_app)])
def test_jm_my_core_todo_creation_screen_major_buttons_fit_desktop_1440(
    optional_chromium_browser, app_name, app
):
    html_response = run_async(_fetch_core_todo_html(app_name, app))
    assert 'id="addForm"' in html_response
    assert 'id="addFormOptions"' in html_response
    assert 'action="/todos"' in html_response
    assert 'method="POST"' in html_response
    assert 'type="submit"' in html_response
    assert 'type="reset"' in html_response
    assert 'aria-label="새 업무 제목"' in html_response
    assert 'aria-label="마감일"' in html_response
    assert 'aria-label="우선순위"' in html_response
    assert 'aria-label="카테고리"' in html_response
    assert 'aria-label="반복 설정"' in html_response
    assert 'aria-label="에너지 레벨"' in html_response
    assert 'aria-label="태그"' in html_response
    assert 'aria-label="알림 시간 선택"' in html_response
    assert 'data-action="toggle-desc-field"' in html_response
    assert 'data-action="add-new-todo-offset"' in html_response

    if optional_chromium_browser is None:
        _assert_static_desktop_containment_contract(app_name, html_response)
        return

    html = _inline_render_css(app_name, html_response)
    context = optional_chromium_browser.new_context(
        viewport=DESKTOP_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.locator("#addFormOptions").evaluate("element => { element.open = true; }")
    page.wait_for_timeout(100)

    metrics = _desktop_creation_button_containment_metrics(page)
    assert metrics["viewportWidth"] == 1440
    assert metrics["checkedCount"] == 13
    assert metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, metrics
    assert metrics["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, metrics
    assert metrics["form"]["right"] <= DESKTOP_VIEWPORT["width"] + 2, metrics
    assert not metrics["form"]["hasHorizontalScroll"], metrics
    assert not metrics["failures"], (
        f"{app_name} /todos#new: creation buttons or action controls are clipped "
        f"or outside add form: {metrics}"
    )

    page.close()
    context.close()


@pytest.mark.parametrize("app_name,app", [("jm", jm_app), ("my", my_app)])
def test_jm_my_core_todo_list_major_buttons_fit_desktop_1440(
    optional_chromium_browser, app_name, app
):
    html_response = run_async(_fetch_core_todo_html(app_name, app))
    assert 'id="todoPage"' in html_response
    assert 'id="addForm"' in html_response
    assert 'id="bulkToggle"' in html_response
    assert 'data-action="toggle-desc-field"' in html_response

    if optional_chromium_browser is None:
        _assert_static_desktop_containment_contract(app_name, html_response)
        assert 'href="/todos/kanban"' in html_response
        assert 'type="submit"' in html_response
        assert 'data-action="add-new-todo-offset"' in html_response
        return

    html = _inline_render_css(app_name, html_response)
    context = optional_chromium_browser.new_context(
        viewport=DESKTOP_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.locator("#addFormOptions").evaluate("element => { element.open = true; }")
    page.wait_for_timeout(100)

    metrics = _desktop_button_containment_metrics(page)
    assert metrics["viewportWidth"] == 1440
    assert metrics["checkedCount"] == 9
    assert not metrics["failures"], (
        f"{app_name} /todos: major buttons are clipped or outside containers: {metrics}"
    )

    page.close()
    context.close()


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_list_item_action_controls_fit_desktop_1440(
    optional_chromium_browser, app_name, app, mod
):
    list_html, edit_html, todo_id = run_async(
        _fetch_core_todo_edit_screen_html(app_name, app, mod)
    )
    assert f'id="todo-{todo_id}"' in list_html
    assert 'class="todo-complete-toggle' in list_html
    assert 'data-action="toggle-subtask-form"' in list_html
    assert f'hx-get="/todos/{todo_id}/edit"' in list_html
    assert f'hx-delete="/todos/{todo_id}"' in list_html
    assert f'id="editTodoForm-{todo_id}"' in edit_html

    if optional_chromium_browser is None:
        _assert_static_desktop_edit_containment_contract(
            app_name, list_html, edit_html, todo_id
        )
        assert "todo-action-bar" in list_html
        assert "todo-action-btn" in list_html
        return

    html = _inline_render_css(app_name, list_html)
    context = optional_chromium_browser.new_context(
        viewport=DESKTOP_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.locator(f"#todo-{todo_id}").focus()
    page.wait_for_timeout(150)

    metrics = _desktop_list_item_action_containment_metrics(page, todo_id)
    assert metrics["viewportWidth"] == 1440
    assert metrics["checkedCount"] == 4
    assert not metrics["failures"], (
        f"{app_name} /todos: list item action controls are clipped or outside card: {metrics}"
    )

    page.close()
    context.close()


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_edit_save_major_buttons_fit_desktop_1440(
    optional_chromium_browser, app_name, app, mod
):
    list_html, edit_html, todo_id = run_async(
        _fetch_core_todo_edit_screen_html(app_name, app, mod)
    )
    assert f'id="todo-{todo_id}"' in list_html
    assert f'id="editTodoForm-{todo_id}"' in edit_html
    assert f'form="editTodoForm-{todo_id}"' in edit_html
    assert "저장" in edit_html

    if optional_chromium_browser is None:
        _assert_static_desktop_edit_containment_contract(
            app_name, list_html, edit_html, todo_id
        )
        return

    html = _inline_render_css(app_name, list_html)
    context = optional_chromium_browser.new_context(
        viewport=DESKTOP_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.locator(f"#todo-{todo_id}").evaluate(
        "(element, editHtml) => { element.outerHTML = editHtml; }",
        edit_html,
    )
    page.wait_for_timeout(100)

    metrics = _desktop_edit_button_containment_metrics(page, todo_id)
    assert metrics["viewportWidth"] == 1440
    assert metrics["viewportHeight"] == 900
    assert metrics["checkedCount"] == 16
    assert metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, metrics
    assert metrics["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, metrics
    assert metrics["containers"]["card"]["right"] <= DESKTOP_VIEWPORT["width"] + 2, metrics
    assert metrics["containers"]["form"]["right"] <= DESKTOP_VIEWPORT["width"] + 2, metrics
    assert metrics["containers"]["actionRow"]["right"] <= DESKTOP_VIEWPORT["width"] + 2, metrics
    assert not metrics["containers"]["card"]["hasHorizontalScroll"], metrics
    assert not metrics["containers"]["form"]["hasHorizontalScroll"], metrics
    assert not metrics["containers"]["actionRow"]["hasHorizontalScroll"], metrics
    assert not metrics["failures"], (
        f"{app_name} /todos/{todo_id}/edit at 1440x900: edit/save buttons "
        f"or action controls are clipped or outside the edited card: {metrics}"
    )

    page.close()
    context.close()
