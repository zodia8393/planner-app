"""
1440x900 desktop button-containment check for jm/my dashboards.

The apps are imported through conftest.py with isolated temp databases. The
rendered check loads the actual dashboard HTML and CSS in Chromium when
available, then verifies that visible dashboard controls stay inside their
containers and inside the desktop viewport.
"""

import pytest

from conftest import jm_app, jm_mod, my_app, my_mod, run_async
from test_dashboard_desktop_horizontal_scroll import (
    DESKTOP_VIEWPORT,
    _assert_static_horizontal_scroll_contract,
    _fetch_dashboard_html,
    _inline_render_css,
    optional_chromium_browser,
)


def _dashboard_desktop_button_containment_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const selectors = [
                ['quickTodo', '.dashboard-quick-actions a[href="/todos#new"]', '.dashboard-quick-actions'],
                ['quickEvent', '.dashboard-quick-actions a[href="/calendar#new"]', '.dashboard-quick-actions'],
                ['quickMemo', '.dashboard-quick-actions a[href="/memos#new"]', '.dashboard-quick-actions'],
                ['emptyTodo', '#dashboard-empty-state a[href="/todos#new"]', '#dashboard-empty-state'],
                ['quickAddTitle', '#quickAddForm input[name="title"]', '#quickAddForm'],
                ['quickAddSubmit', '#quickAddForm button[type="submit"]', '#quickAddForm'],
                ['notificationToggle', '.common-app-header [data-action="toggle-notif-panel"]', '.common-app-header'],
                ['focusLauncher', '#focusBtn', 'body'],
            ];
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number.parseFloat(style.opacity || '1') > 0.01
                    && rect.width > 1
                    && rect.height > 1
                    && rect.bottom > 0
                    && rect.top < viewportHeight;
            };
            const labelFor = (el) => (
                el.getAttribute('aria-label') ||
                el.getAttribute('title') ||
                el.getAttribute('placeholder') ||
                el.value ||
                el.innerText ||
                el.textContent ||
                ''
            ).trim().replace(/\\s+/g, ' ');
            const childOverflowFor = (el, rect) => Array.from(
                el.querySelectorAll('svg, img, span, strong, em, small')
            )
                .filter((child) => {
                    const childStyle = window.getComputedStyle(child);
                    const childRect = child.getBoundingClientRect();
                    if (
                        childStyle.display === 'none' ||
                        childStyle.visibility === 'hidden' ||
                        childRect.width <= 0 ||
                        childRect.height <= 0
                    ) return false;
                    return childRect.left < rect.left - 2
                        || childRect.right > rect.right + 2
                        || childRect.top < rect.top - 2
                        || childRect.bottom > rect.bottom + 2;
                })
                .slice(0, 4)
                .map((child) => {
                    const childRect = child.getBoundingClientRect();
                    return {
                        tag: child.tagName.toLowerCase(),
                        text: (child.innerText || child.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 60),
                        left: Math.round(childRect.left),
                        right: Math.round(childRect.right),
                        top: Math.round(childRect.top),
                        bottom: Math.round(childRect.bottom),
                    };
                });
            const describe = ([name, selector, containerSelector]) => {
                const container = document.querySelector(containerSelector);
                const el = document.querySelector(selector);
                if (!el || !container) {
                    return { name, selector, containerSelector, missing: true };
                }
                const rect = el.getBoundingClientRect();
                const containerRect = container.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                const clipsOwnContent = (
                    (style.overflowX !== 'visible' && el.scrollWidth > el.clientWidth + 2) ||
                    (style.overflowY !== 'visible' && el.scrollHeight > el.clientHeight + 2)
                );
                return {
                    name,
                    selector,
                    containerSelector,
                    label: labelFor(el).slice(0, 90),
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
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    outsideViewport: rect.left < -2
                        || rect.right > viewportWidth + 2
                        || rect.top < -2
                        || rect.bottom > viewportHeight + 2,
                    outsideContainer: rect.left < containerRect.left - 2
                        || rect.right > containerRect.right + 2
                        || rect.top < containerRect.top - 2
                        || rect.bottom > containerRect.bottom + 2,
                    clipsOwnContent,
                    childOverflow: childOverflowFor(el, rect),
                };
            };
            const checks = selectors.map(describe);
            return {
                viewportWidth,
                viewportHeight,
                checkedCount: checks.length,
                labels: checks.map((item) => item.label || '').filter(Boolean),
                failures: checks.filter((item) =>
                    item.missing ||
                    !item.visible ||
                    item.width < 24 ||
                    item.height < 24 ||
                    item.outsideViewport ||
                    item.outsideContainer ||
                    item.clipsOwnContent ||
                    item.childOverflow?.length > 0
                ),
                checks,
            };
        }"""
    )


def _assert_static_desktop_button_containment_contract(app_name: str, html: str) -> None:
    _assert_static_horizontal_scroll_contract(app_name, html)
    assert 'aria-label="빠른 작업"' in html
    assert 'href="/todos#new"' in html
    assert 'href="/calendar#new"' in html
    assert 'href="/memos#new"' in html
    assert 'id="quickAddForm"' in html
    assert 'name="title"' in html
    assert 'type="submit"' in html
    assert 'id="focusBtn"' in html
    assert 'data-action="toggle-notif-panel"' in html


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_desktop_1440_buttons_and_actions_stay_inside_containers(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    _assert_static_desktop_button_containment_contract(app_name, html_response)

    if optional_chromium_browser is None:
        return

    context = optional_chromium_browser.new_context(
        viewport=DESKTOP_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page.set_content(_inline_render_css(app_name, html_response), wait_until="domcontentloaded")
    page.wait_for_timeout(100)
    metrics = _dashboard_desktop_button_containment_metrics(page)

    assert metrics["viewportWidth"] == DESKTOP_VIEWPORT["width"], metrics
    assert metrics["viewportHeight"] == DESKTOP_VIEWPORT["height"], metrics
    assert metrics["checkedCount"] == 8, metrics
    assert any("할일" in label for label in metrics["labels"]), (
        f"{app_name} /: core todo entry button was not rendered: {metrics}"
    )
    assert any("빠른 업무 추가" in label for label in metrics["labels"]), (
        f"{app_name} /: quick-add input was not rendered: {metrics}"
    )
    assert not metrics["failures"], (
        f"{app_name} / at 1440x900: dashboard buttons or action controls are "
        f"clipped or outside containers: {metrics}"
    )

    page.close()
    context.close()
