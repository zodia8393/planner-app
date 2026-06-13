"""
Independent 390x844 responsive UI check for the jm/my first-entry core list.

The selected MVP core list for both planner instances is /todos. The app
fixtures use isolated temporary databases, so the visible test todo is not
written to production data.
"""

import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from conftest import jm_app, jm_mod, my_app, my_mod, run_async


try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:
    PlaywrightError = None
    sync_playwright = None


ROOT = Path(__file__).resolve().parents[1]
MOBILE_VIEWPORT = {"width": 390, "height": 844}
ORIGIN = {"origin": "http://testserver", "host": "testserver"}


def _can_launch_chromium() -> bool:
    if sync_playwright is None:
        return False

    script = """
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(timeout=3000)
    browser.close()
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=6,
        )
    except (subprocess.SubprocessError, TimeoutError):
        return False
    return result.returncode == 0


@pytest.fixture(scope="module")
def optional_chromium_browser():
    if not _can_launch_chromium():
        yield None
        return

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(timeout=5000)
        except PlaywrightError:
            yield None
            return
        yield browser
        browser.close()


def _asset_text(app_name: str, relative_path: str) -> str:
    return (ROOT / app_name / relative_path).read_text(encoding="utf-8")


def _inline_render_css(app_name: str, html: str) -> str:
    css = "\n".join(
        [
            _asset_text(app_name, "static/tailwind.css"),
            _asset_text(app_name, "static/css/app.css"),
        ]
    )
    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r'<script\b[^>]*\bsrc="[^"]+"[^>]*></script>', "", html)
    test_css = """
        *, *::before, *::after {
            animation: none !important;
            transition: none !important;
            caret-color: transparent !important;
        }
    """
    return html.replace("</head>", f"<style>{css} {test_css}</style></head>")


def _insert_visible_todo(mod, profile_id: int, app_name: str) -> int:
    title = f"{app_name} first entry mobile responsive verification {uuid4().hex[:10]}"
    with mod.get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM todos WHERE profile_id=?",
            (profile_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO todos (
                profile_id, title, description, priority, due_date, tags,
                energy_level, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                title,
                "390x844 rendered core list item for overflow, overlap, and button clipping.",
                1,
                "2026-06-12",
                '["mvp-first-entry-mobile"]',
                3,
                max_order + 1,
            ),
        )
        todo_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO subtasks (todo_id, title, sort_order) VALUES (?, ?, ?)",
            (todo_id, "Confirm responsive bounds", 1),
        )
        return todo_id


async def _fetch_first_entry_core_list_html(app_name: str, app, mod) -> tuple[str, int]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"FirstEntryMobile{uuid4().hex[:8]}"
            response = await client.post(
                "/setup",
                data={"name": profile_name},
                headers=ORIGIN,
                follow_redirects=False,
            )
            assert response.status_code == 303
            with mod.get_db() as conn:
                row = conn.execute(
                    "SELECT id FROM profiles WHERE name=?",
                    (profile_name,),
                ).fetchone()
            assert row is not None
            profile_id = int(row["id"])

        todo_id = _insert_visible_todo(mod, profile_id, app_name)
        response = await client.get("/todos")
        assert response.status_code == 200, f"{app_name} /todos: {response.status_code}"
        assert f'id="todo-{todo_id}"' in response.text
        return response.text, todo_id


def _assert_static_first_entry_mobile_contract(
    app_name: str,
    html: str,
    todo_id: int,
) -> None:
    app_css = _asset_text(app_name, "static/css/app.css")

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}
    assert 'role="main"' in html
    assert 'id="mainContent"' in html
    assert 'id="todoPage"' in html
    assert 'id="todoList"' in html
    assert 'aria-label="할일 목록"' in html
    assert f'id="todo-{todo_id}"' in html
    assert "업무 관리" in html
    assert "목록 보기" in html
    assert "정렬/필터" in html
    assert "first entry mobile responsive verification" in html

    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert ".flex { min-width: 0; }" in app_css
    assert ".flex > * { min-width: 0; }" in app_css
    assert "#todoPage :where(.btn-sm, .btn-accent, .todo-action-btn, .todo-complete-toggle)" in app_css
    assert "#todoPage .todo-action-bar" in app_css
    assert "justify-content: flex-end;" in app_css


def _first_entry_mobile_metrics(page, todo_id: int):
    return page.evaluate(
        """(todoId) => {
            const viewportWidth = window.innerWidth;
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
            const allowedScrollable = (el) =>
                Boolean(el.closest('#sidebar, .overflow-x-auto, .table-responsive'));
            const rectSummary = (name, el) => {
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    name,
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    width: Math.round(rect.width),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    overflowBy: Math.max(0, el.scrollWidth - el.clientWidth),
                };
            };
            const textFor = (el) => {
                if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                    return el.value || el.placeholder || el.getAttribute('aria-label') || '';
                }
                if (el instanceof HTMLSelectElement) {
                    return el.getAttribute('aria-label') || el.options[el.selectedIndex]?.text || '';
                }
                return Array.from(el.childNodes)
                    .filter((node) => node.nodeType === Node.TEXT_NODE)
                    .map((node) => node.textContent.trim())
                    .filter(Boolean)
                    .join(' ')
                    .replace(/\\s+/g, ' ')
                    .trim();
            };
            const containers = [
                rectSummary('documentElement', document.documentElement),
                rectSummary('body', document.body),
                rectSummary('main', document.querySelector('main[role="main"]')),
                rectSummary('mainContent', document.querySelector('#mainContent')),
                rectSummary('todoPage', document.querySelector('#todoPage')),
                rectSummary('todoList', document.querySelector('#todoList')),
            ].filter(Boolean);

            const textCandidates = Array.from(document.querySelectorAll([
                '.common-app-header h2',
                '.common-app-header p',
                '#todoPage h1',
                '#todoPage h2',
                '#todoPage h3',
                '#todoPage p',
                '#todoPage summary',
                '#todoPage label',
                '#todoPage button',
                '#todoPage input',
                '#todoPage select',
                '#todoList article p',
                '#todoList article span',
                '#todoList article a',
                '#todoList .text-xs',
                '#todoList .text-sm',
                '#todoList .font-medium'
            ].join(',')))
                .filter((el) => el instanceof HTMLElement && visible(el) && !allowedScrollable(el))
                .filter((el) => textFor(el));
            const textRects = [];
            textCandidates.forEach((el, index) => {
                const text = textFor(el).slice(0, 90);
                const container = el.closest('.work-card, article, section, form, details, #mainContent, main');
                const containerRect = container ? container.getBoundingClientRect() : null;
                Array.from(el.getClientRects()).forEach((rect, rectIndex) => {
                    if (rect.width <= 1 || rect.height <= 1) return;
                    textRects.push({
                        el,
                        key: `${index}:${rectIndex}`,
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 120),
                        text,
                        left: rect.left,
                        right: rect.right,
                        top: rect.top,
                        bottom: rect.bottom,
                        width: rect.width,
                        height: rect.height,
                        container: container ? {
                            tag: container.tagName.toLowerCase(),
                            id: container.id || '',
                            className: String(container.className || '').slice(0, 120),
                            left: containerRect.left,
                            right: containerRect.right,
                        } : null,
                    });
                });
            });

            const overlaps = [];
            for (let i = 0; i < textRects.length; i += 1) {
                for (let j = i + 1; j < textRects.length; j += 1) {
                    const a = textRects[i];
                    const b = textRects[j];
                    if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
                    const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                    const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                    if (x <= 1 || y <= 1) continue;
                    const area = x * y;
                    const smaller = Math.min(a.width * a.height, b.width * b.height);
                    if (area > 4 && area / smaller > 0.03) {
                        overlaps.push({
                            first: {
                                tag: a.tag,
                                id: a.id,
                                className: a.className,
                                text: a.text,
                                box: [Math.round(a.left), Math.round(a.top), Math.round(a.right), Math.round(a.bottom)],
                            },
                            second: {
                                tag: b.tag,
                                id: b.id,
                                className: b.className,
                                text: b.text,
                                box: [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom)],
                            },
                        });
                    }
                }
            }

            const textOverflow = textRects
                .filter((item) => {
                    if (item.left < -2 || item.right > viewportWidth + 2) return true;
                    if (!item.container) return false;
                    return item.left < item.container.left - 2 || item.right > item.container.right + 2;
                })
                .slice(0, 10)
                .map((item) => ({
                    tag: item.tag,
                    id: item.id,
                    className: item.className,
                    text: item.text,
                    left: Math.round(item.left),
                    right: Math.round(item.right),
                    container: item.container ? {
                        tag: item.container.tag,
                        id: item.container.id,
                        className: item.container.className,
                        left: Math.round(item.container.left),
                        right: Math.round(item.container.right),
                    } : null,
                }));

            const buttonSelectors = [
                ['listView', 'a[href="/todos"]', '#todoPage'],
                ['kanbanView', 'a[href="/todos/kanban"]', '#todoPage'],
                ['filterAll', 'a[href^="/todos?filter=all"]', '#todoPage'],
                ['filterActive', 'a[href^="/todos?filter=active"]', '#todoPage'],
                ['filterCompleted', 'a[href^="/todos?filter=completed"]', '#todoPage'],
                ['bulkToggle', '#bulkToggle', '#todoPage'],
                ['addSubmit', '#addForm button[type="submit"]', '#addForm'],
                ['addCancel', '#addForm button[type="reset"]', '#addForm'],
                ['completeToggle', `#todo-${todoId} .todo-complete-toggle`, `#todo-${todoId}`],
                ['subtask', `#todo-${todoId} [data-action="toggle-subtask-form"]`, `#todo-${todoId}`],
                ['edit', `#todo-${todoId} button[aria-label="편집"]`, `#todo-${todoId}`],
                ['delete', `#todo-${todoId} button[aria-label="삭제"]`, `#todo-${todoId}`],
            ];
            const buttons = buttonSelectors.map(([name, selector, containerSelector]) => {
                const container = document.querySelector(containerSelector);
                const el = container ? container.querySelector(selector) : null;
                if (!el || !container) return { name, selector, containerSelector, missing: true };
                const rect = el.getBoundingClientRect();
                const containerRect = container.getBoundingClientRect();
                return {
                    name,
                    selector,
                    label: (el.getAttribute('aria-label') || el.textContent || '').replace(/\\s+/g, ' ').trim(),
                    visible: visible(el),
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    top: Math.round(rect.top),
                    bottom: Math.round(rect.bottom),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    containerLeft: Math.round(containerRect.left),
                    containerRight: Math.round(containerRect.right),
                    clippedByViewport: rect.left < -2 || rect.right > viewportWidth + 2,
                    outsideContainer:
                        rect.left < containerRect.left - 2
                        || rect.right > containerRect.right + 2
                        || rect.top < containerRect.top - 2
                        || rect.bottom > containerRect.bottom + 2,
                };
            });
            const visibleOffenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => el instanceof HTMLElement && visible(el) && !allowedScrollable(el))
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 120),
                        left: Math.round(rect.left),
                        right: Math.round(rect.right),
                        width: Math.round(rect.width),
                    };
                })
                .filter((item) => item.width > 0 && (item.left < -2 || item.right > viewportWidth + 2))
                .slice(0, 10);

            return {
                viewportWidth,
                viewportHeight: window.innerHeight,
                textElementCount: textRects.length,
                containers,
                visibleOffenders,
                textOverflow,
                overlaps: overlaps.slice(0, 10),
                buttons,
                buttonFailures: buttons.filter((button) =>
                    button.missing
                    || !button.visible
                    || button.width < 24
                    || button.height < 24
                    || button.clippedByViewport
                    || button.outsideContainer
                ),
            };
        }""",
        todo_id,
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_first_entry_core_todo_list_mobile_390x844_has_no_scroll_overlap_or_clipped_buttons(
    optional_chromium_browser,
    app_name,
    app,
    mod,
):
    html_response, todo_id = run_async(
        _fetch_first_entry_core_list_html(app_name, app, mod)
    )
    _assert_static_first_entry_mobile_contract(app_name, html_response, todo_id)

    if optional_chromium_browser is None:
        return

    context = optional_chromium_browser.new_context(
        viewport=MOBILE_VIEWPORT,
        java_script_enabled=False,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda err, _errors=page_errors: _errors.append(str(err)))
    page.set_content(
        _inline_render_css(app_name, html_response),
        wait_until="domcontentloaded",
        timeout=10000,
    )
    page.wait_for_timeout(100)

    metrics = _first_entry_mobile_metrics(page, todo_id)
    assert metrics["viewportWidth"] == MOBILE_VIEWPORT["width"], metrics
    assert metrics["viewportHeight"] == MOBILE_VIEWPORT["height"], metrics
    assert metrics["textElementCount"] >= 18, metrics
    assert not metrics["visibleOffenders"], (
        f"{app_name} /todos: visible elements exceed the 390px viewport: {metrics}"
    )
    for container in metrics["containers"]:
        assert container["right"] <= MOBILE_VIEWPORT["width"] + 2, metrics
        assert container["overflowBy"] <= 2, (
            f"{app_name} /todos: {container['name']} has horizontal scroll at 390x844: {metrics}"
        )
    assert not metrics["textOverflow"], (
        f"{app_name} /todos: text exceeds its viewport/container at 390x844: {metrics}"
    )
    assert not metrics["overlaps"], (
        f"{app_name} /todos: text elements overlap at 390x844: {metrics}"
    )
    assert not metrics["buttonFailures"], (
        f"{app_name} /todos: buttons are clipped, hidden, or outside containers at 390x844: {metrics}"
    )
    page_errors = [err for err in page_errors if "localStorage" not in err]
    assert not page_errors, f"{app_name} /todos: page errors: {page_errors}"

    page.close()
    context.close()
