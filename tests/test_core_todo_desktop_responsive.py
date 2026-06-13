"""
Desktop UI overflow checks for the jm/my MVP core todo list screens.

The apps come from conftest.py with isolated temp databases, so this test does
not touch production data.
"""

import asyncio
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from conftest import run_async, jm_app, jm_mod, my_app, my_mod


try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:
    PlaywrightError = None
    sync_playwright = None


DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
ORIGIN = {"origin": "http://testserver", "host": "testserver"}
ROOT = Path(__file__).resolve().parents[1]


def _can_launch_chromium() -> bool:
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
    if sync_playwright is None:
        yield None
        return
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
        if browser is not None:
            browser.close()


async def _fetch_core_todo_html(app_name: str, app) -> str:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        if app_name == "my":
            response = await client.post(
                "/setup",
                data={"name": f"CoreTodoDesktop{uuid4().hex[:8]}"},
                headers=ORIGIN,
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert client.cookies.get("planner_profile")

        response = await client.get("/todos")
        assert response.status_code == 200, f"{app_name} /todos: status {response.status_code}"
        return response.text


def _insert_desktop_edit_todo(mod, profile_id: int, title: str) -> int:
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
                "Desktop edit overflow verification item.",
                2,
                "2026-06-12",
                '["mvp-desktop-edit"]',
                max_order + 1,
            ),
        )
        return int(cur.lastrowid)


async def _fetch_core_todo_edit_screen_html(app_name: str, app, mod) -> tuple[str, str, int]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"CoreTodoDesktopEdit{uuid4().hex[:8]}"
            response = await client.post(
                "/setup",
                data={"name": profile_name},
                headers=ORIGIN,
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert client.cookies.get("planner_profile")
            with mod.get_db() as conn:
                row = conn.execute(
                    "SELECT id FROM profiles WHERE name=?",
                    (profile_name,),
                ).fetchone()
            assert row is not None
            profile_id = int(row["id"])

        todo_id = _insert_desktop_edit_todo(
            mod,
            profile_id,
            f"{app_name} desktop edit save flow responsive todo {uuid4().hex}",
        )

        list_response = await client.get("/todos")
        assert list_response.status_code == 200, (
            f"{app_name} /todos: status {list_response.status_code}"
        )
        assert f'id="todo-{todo_id}"' in list_response.text

        edit_response = await client.get(
            f"/todos/{todo_id}/edit",
            headers={**ORIGIN, "HX-Request": "true"},
        )
        assert edit_response.status_code == 200, (
            f"{app_name} /todos/{todo_id}/edit: status {edit_response.status_code}"
        )
        assert f'id="editTodoForm-{todo_id}"' in edit_response.text
        assert f'hx-put="/todos/{todo_id}"' in edit_response.text

        return list_response.text, edit_response.text, todo_id


def _app_css(app_name: str, relative_path: str) -> str:
    return (ROOT / app_name / relative_path).read_text(encoding="utf-8")


def _inline_render_css(app_name: str, html: str) -> str:
    css_chunks = [
        _app_css(app_name, "static/tailwind.css"),
        _app_css(app_name, "static/css/app.css"),
    ]

    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r'<script\b[^>]*\bsrc="[^"]+"[^>]*></script>', "", html)
    inline_css = "<style>" + "\n".join(css_chunks) + "</style>"
    return html.replace("</head>", f"{inline_css}</head>")


def _assert_static_desktop_containment_contract(app_name: str, html: str) -> None:
    app_css = _app_css(app_name, "static/css/app.css")

    assert 'id="mainContent"' in html
    assert 'id="addForm"' in html
    assert 'id="todoList"' in html
    assert 'aria-label="할일 목록"' in html
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "*, *::before, *::after { box-sizing: border-box; }" in app_css
    assert "#mainContent {" in app_css
    assert "max-width: 100%" in app_css
    assert "min-width: 0" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert ".work-card" in app_css, app_name


def _assert_static_desktop_edit_containment_contract(
    app_name: str, list_html: str, edit_html: str, todo_id: int
) -> None:
    _assert_static_desktop_containment_contract(app_name, list_html)
    app_css = _app_css(app_name, "static/css/app.css")

    assert f'id="todo-{todo_id}"' in edit_html
    assert f'id="editTodoForm-{todo_id}"' in edit_html
    assert f'hx-put="/todos/{todo_id}"' in edit_html
    assert 'aria-label="할일 제목"' in edit_html
    assert 'aria-label="설명"' in edit_html
    assert 'aria-label="마감일"' in edit_html
    assert 'aria-label="우선순위"' in edit_html
    assert 'aria-label="알림 시간 선택"' in edit_html
    assert 'form="editTodoForm-' in edit_html
    assert "input, select, textarea { max-width: 100%; box-sizing: border-box; }" in app_css


def _core_todo_desktop_overflow_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const selectors = {
                documentElement: 'html',
                body: 'body',
                main: 'main[role="main"]',
                mainContent: '#mainContent',
                addForm: '#addForm',
                todoListSection: 'section[aria-label="할일 목록"]',
                todoList: '#todoList',
            };
            const rectFor = (selector) => {
                const el = document.querySelector(selector);
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    selector,
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    hasHorizontalScroll: el.scrollWidth > el.clientWidth + 2,
                };
            };
            const allowedScrollable = (el) => {
                if (!el || !(el instanceof HTMLElement)) return false;
                return Boolean(el.closest('.overflow-x-auto, .table-responsive'));
            };
            const offenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return false;
                    if (allowedScrollable(el)) return false;
                    return rect.left < -2 || rect.right > viewportWidth + 2;
                })
                .slice(0, 8)
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 140),
                        left: Math.round(rect.left),
                        right: Math.round(rect.right),
                        scrollWidth: el.scrollWidth,
                        clientWidth: el.clientWidth,
                    };
                });

            return {
                viewportWidth,
                viewportHeight: window.innerHeight,
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                containers: Object.fromEntries(
                    Object.entries(selectors).map(([key, selector]) => [key, rectFor(selector)])
                ),
                visibleTextLength: document.querySelector('#mainContent')?.innerText.trim().length || 0,
                offenders,
            };
        }"""
    )


def _core_todo_edit_desktop_overflow_metrics(page, todo_id: int):
    return page.evaluate(
        """(todoId) => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const selectors = {
                main: 'main[role="main"]',
                mainContent: '#mainContent',
                editedCard: `#todo-${todoId}`,
                editForm: `#editTodoForm-${todoId}`,
                fieldRow: `#editTodoForm-${todoId} > div.flex.flex-wrap`,
                reminderControls: `#todoOffsetSel_${todoId}`,
                actionRow: `#todo-${todoId} > div.flex.justify-end`,
            };
            const rectFor = (selector) => {
                const el = document.querySelector(selector);
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    selector,
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    hasHorizontalScroll: el.scrollWidth > el.clientWidth + 2,
                };
            };
            const allowedScrollable = (el) => {
                if (!el || !(el instanceof HTMLElement)) return false;
                return Boolean(el.closest('.overflow-x-auto, .table-responsive'));
            };
            const offenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return false;
                    if (allowedScrollable(el)) return false;
                    return rect.left < -2 || rect.right > viewportWidth + 2;
                })
                .slice(0, 8)
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 140),
                        left: Math.round(rect.left),
                        right: Math.round(rect.right),
                        scrollWidth: el.scrollWidth,
                        clientWidth: el.clientWidth,
                    };
                });

            return {
                viewportWidth,
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                containers: Object.fromEntries(
                    Object.entries(selectors).map(([key, selector]) => [key, rectFor(selector)])
                ),
                editTextLength: document.querySelector(`#editTodoForm-${todoId}`)?.innerText.trim().length || 0,
                offenders,
            };
        }""",
        todo_id,
    )


def _core_todo_creation_desktop_overflow_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const selectors = {
                documentElement: 'html',
                body: 'body',
                main: 'main[role="main"]',
                mainContent: '#mainContent',
                addForm: '#addForm',
                addFormForm: '#addForm form',
                titleRow: '#addForm form > .flex',
                addOptions: '#addFormOptions',
                optionControls: '#addFormOptions > div.flex',
                reminderControls: '#newTodoOffsetSel',
            };
            const rectFor = (selector) => {
                const el = document.querySelector(selector);
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    selector,
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    hasHorizontalScroll: el.scrollWidth > el.clientWidth + 2,
                };
            };
            const allowedScrollable = (el) => {
                if (!el || !(el instanceof HTMLElement)) return false;
                return Boolean(el.closest('.overflow-x-auto, .table-responsive'));
            };
            const offenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return false;
                    if (allowedScrollable(el)) return false;
                    return rect.left < -2 || rect.right > viewportWidth + 2;
                })
                .slice(0, 8)
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 140),
                        left: Math.round(rect.left),
                        right: Math.round(rect.right),
                        scrollWidth: el.scrollWidth,
                        clientWidth: el.clientWidth,
                    };
                });

            return {
                viewportWidth,
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                containers: Object.fromEntries(
                    Object.entries(selectors).map(([key, selector]) => [key, rectFor(selector)])
                ),
                creationTextLength: document.querySelector('#addForm')?.innerText.trim().length || 0,
                offenders,
            };
        }"""
    )


@pytest.mark.parametrize("app_name,app", [("jm", jm_app), ("my", my_app)])
def test_jm_my_core_todo_list_desktop_1440_has_no_horizontal_scroll(
    optional_chromium_browser, app_name, app
):
    html_response = run_async(_fetch_core_todo_html(app_name, app))
    assert 'id="addForm"' in html_response
    assert 'id="todoList"' in html_response

    if optional_chromium_browser is None:
        _assert_static_desktop_containment_contract(app_name, html_response)
        return

    html = _inline_render_css(app_name, html_response)
    context = optional_chromium_browser.new_context(
        viewport=DESKTOP_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda err, _e=page_errors: _e.append(str(err)))
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    metrics = _core_todo_desktop_overflow_metrics(page)
    assert metrics["viewportWidth"] == 1440, f"{app_name} /todos: wrong viewport: {metrics}"
    assert metrics["viewportHeight"] == 900, f"{app_name} /todos: wrong viewport: {metrics}"
    assert metrics["visibleTextLength"] > 20, f"{app_name} /todos: primary content is blank"
    assert metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /todos: document overflows desktop viewport: {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /todos: body overflows desktop viewport: {metrics}"
    )

    for key, rect in metrics["containers"].items():
        assert rect, f"{app_name} /todos: missing {key}: {metrics}"
        assert rect["right"] <= DESKTOP_VIEWPORT["width"] + 2, (
            f"{app_name} /todos: {key} exceeds 1440px viewport: {metrics}"
        )
        assert not rect["hasHorizontalScroll"], (
            f"{app_name} /todos: {key} has internal horizontal scroll: {metrics}"
        )

    assert not metrics["offenders"], (
        f"{app_name} /todos: visible elements exceed 1440px viewport: {metrics}"
    )
    assert not page_errors, f"{app_name} /todos: page errors: {page_errors}"

    page.close()
    context.close()


@pytest.mark.parametrize("app_name,app", [("jm", jm_app), ("my", my_app)])
def test_jm_my_core_todo_creation_screen_desktop_1440_has_no_horizontal_scroll(
    optional_chromium_browser, app_name, app
):
    html_response = run_async(_fetch_core_todo_html(app_name, app))
    assert 'id="addForm"' in html_response
    assert 'id="addFormOptions"' in html_response
    assert 'action="/todos"' in html_response
    assert 'name="title"' in html_response
    assert 'aria-label="새 업무 제목"' in html_response

    if optional_chromium_browser is None:
        _assert_static_desktop_containment_contract(app_name, html_response)
        assert 'id="newTodoOffsetSel"' in html_response
        assert 'aria-label="알림 시간 선택"' in html_response
        return

    html = _inline_render_css(app_name, html_response)
    context = optional_chromium_browser.new_context(
        viewport=DESKTOP_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda err, _e=page_errors: _e.append(str(err)))
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.locator("#addFormOptions").evaluate("element => { element.open = true; }")
    page.wait_for_timeout(100)

    metrics = _core_todo_creation_desktop_overflow_metrics(page)
    assert metrics["viewportWidth"] == 1440, (
        f"{app_name} /todos#new: wrong viewport: {metrics}"
    )
    assert metrics["creationTextLength"] > 20, (
        f"{app_name} /todos#new: creation form is blank"
    )
    assert metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /todos#new: document overflows desktop viewport: {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /todos#new: body overflows desktop viewport: {metrics}"
    )

    for key, rect in metrics["containers"].items():
        assert rect, f"{app_name} /todos#new: missing {key}: {metrics}"
        assert rect["right"] <= DESKTOP_VIEWPORT["width"] + 2, (
            f"{app_name} /todos#new: {key} exceeds 1440px viewport: {metrics}"
        )
        assert not rect["hasHorizontalScroll"], (
            f"{app_name} /todos#new: {key} has internal horizontal scroll: {metrics}"
        )

    assert not metrics["offenders"], (
        f"{app_name} /todos#new: visible elements exceed 1440px viewport: {metrics}"
    )
    assert not page_errors, f"{app_name} /todos#new: page errors: {page_errors}"

    page.close()
    context.close()


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_edit_save_screen_desktop_1440_has_no_horizontal_scroll(
    optional_chromium_browser, app_name, app, mod
):
    list_html, edit_html, todo_id = run_async(
        _fetch_core_todo_edit_screen_html(app_name, app, mod)
    )
    assert f'id="todo-{todo_id}"' in list_html
    assert f'id="editTodoForm-{todo_id}"' in edit_html
    assert 'aria-label="할일 제목"' in edit_html
    assert 'aria-label="설명"' in edit_html
    assert 'aria-label="마감일"' in edit_html
    assert 'aria-label="우선순위"' in edit_html
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
    page_errors = []
    page.on("pageerror", lambda err, _e=page_errors: _e.append(str(err)))
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.locator(f"#todo-{todo_id}").evaluate(
        "(element, editHtml) => { element.outerHTML = editHtml; }",
        edit_html,
    )
    page.wait_for_timeout(100)

    metrics = _core_todo_edit_desktop_overflow_metrics(page, todo_id)
    assert metrics["viewportWidth"] == 1440, (
        f"{app_name} /todos/{todo_id}/edit: wrong viewport: {metrics}"
    )
    assert metrics["editTextLength"] > 10, (
        f"{app_name} /todos/{todo_id}/edit: edit form is blank"
    )
    assert metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /todos/{todo_id}/edit: document overflows desktop viewport: {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /todos/{todo_id}/edit: body overflows desktop viewport: {metrics}"
    )

    for key, rect in metrics["containers"].items():
        assert rect, f"{app_name} /todos/{todo_id}/edit: missing {key}: {metrics}"
        assert rect["right"] <= DESKTOP_VIEWPORT["width"] + 2, (
            f"{app_name} /todos/{todo_id}/edit: {key} exceeds 1440px viewport: {metrics}"
        )
        assert not rect["hasHorizontalScroll"], (
            f"{app_name} /todos/{todo_id}/edit: {key} has internal horizontal scroll: {metrics}"
        )

    assert not metrics["offenders"], (
        f"{app_name} /todos/{todo_id}/edit: visible elements exceed 1440px viewport: {metrics}"
    )
    assert not page_errors, (
        f"{app_name} /todos/{todo_id}/edit: page errors: {page_errors}"
    )

    page.close()
    context.close()
