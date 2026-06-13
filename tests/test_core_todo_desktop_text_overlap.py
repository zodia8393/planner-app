"""
Desktop text overlap checks for the jm/my MVP core todo list screens.

The apps come from conftest.py with isolated temp databases, so this test does
not touch production data. When Chromium is available, it renders /todos at
1440x900 and checks major visible text elements for overlapping boxes.
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


def _insert_visible_todo(mod, profile_id: int, app_name: str) -> int:
    title = f"{app_name} desktop text overlap verification {uuid4().hex[:10]}"
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
                "Desktop text overlap smoke item for the MVP core todo list.",
                1,
                "2026-06-12",
                '["mvp-desktop-text"]',
                max_order + 1,
            ),
        )
        todo_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO subtasks (todo_id, title, sort_order) VALUES (?, ?, ?)",
            (todo_id, "Review text spacing", 1),
        )
        return todo_id


async def _fetch_core_todo_html_with_visible_item(app_name: str, app, mod) -> tuple[str, int]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"CoreTodoText{uuid4().hex[:8]}"
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

        todo_id = _insert_visible_todo(mod, profile_id, app_name)
        response = await client.get("/todos")
        assert response.status_code == 200, f"{app_name} /todos: status {response.status_code}"
        assert f'id="todo-{todo_id}"' in response.text
        return response.text, todo_id


async def _fetch_core_todo_edit_html_with_visible_item(
    app_name: str, app, mod
) -> tuple[str, str, int]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"CoreTodoEditText{uuid4().hex[:8]}"
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

        todo_id = _insert_visible_todo(mod, profile_id, app_name)
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


def _assert_static_core_todo_text_contract(app_name: str, html: str, todo_id: int) -> None:
    app_css = _app_css(app_name, "static/css/app.css")

    assert 'role="main"' in html
    assert 'id="mainContent"' in html
    assert 'id="todoPage"' in html
    assert 'id="addForm"' in html
    assert 'aria-label="할일 목록"' in html
    assert 'id="todoList"' in html
    assert f'id="todo-{todo_id}"' in html
    assert "업무 관리" in html
    assert "목록 보기" in html
    assert "정렬/필터" in html
    assert "새 업무 제목" in html

    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert ".work-card" in app_css
    assert ".flex { min-width: 0; }" in app_css
    assert ".flex > * { min-width: 0; }" in app_css


def _core_todo_desktop_text_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const selectors = {
                header: '.common-app-header',
                main: 'main[role="main"]',
                mainContent: '#mainContent',
                todoPage: '#todoPage',
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
            const directText = (el) => Array.from(el.childNodes)
                .filter((node) => node.nodeType === Node.TEXT_NODE)
                .map((node) => node.textContent.trim())
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();
            const readableName = (el) => {
                if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                    return el.value || el.placeholder || el.getAttribute('aria-label') || '';
                }
                if (el instanceof HTMLSelectElement) {
                    return el.getAttribute('aria-label') || el.options[el.selectedIndex]?.text || '';
                }
                return directText(el) || '';
            };
            const candidateSelector = [
                '.common-app-header h2',
                '.common-app-header p',
                '.common-app-header .date-badge',
                '#mainContent h1',
                '#mainContent h2',
                '#mainContent h3',
                '#mainContent p',
                '#mainContent summary',
                '#mainContent a',
                '#mainContent button',
                '#mainContent input',
                '#mainContent textarea',
                '#mainContent select',
                '#mainContent label',
                '#todoList article p',
                '#todoList article span',
                '#todoList article a',
                '#todoList .text-xs',
                '#todoList .text-sm',
                '#todoList .font-bold',
                '#todoList .font-medium'
            ].join(',');
            const candidates = Array.from(document.querySelectorAll(candidateSelector))
                .filter((el) => el instanceof HTMLElement)
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    if (Number.parseFloat(style.opacity || '1') <= 0.01) return false;
                    const text = readableName(el);
                    if (!text) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 1 && rect.height > 1;
                });
            const items = [];
            candidates.forEach((el, index) => {
                const text = readableName(el).slice(0, 80);
                Array.from(el.getClientRects()).forEach((rect, rectIndex) => {
                    if (rect.width <= 1 || rect.height <= 1) return;
                    items.push({
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
                    });
                });
            });
            const overlaps = [];
            for (let i = 0; i < items.length; i += 1) {
                for (let j = i + 1; j < items.length; j += 1) {
                    const a = items[i];
                    const b = items[j];
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
                                box: [
                                    Math.round(a.left), Math.round(a.top),
                                    Math.round(a.right), Math.round(a.bottom)
                                ],
                            },
                            second: {
                                tag: b.tag,
                                id: b.id,
                                className: b.className,
                                text: b.text,
                                box: [
                                    Math.round(b.left), Math.round(b.top),
                                    Math.round(b.right), Math.round(b.bottom)
                                ],
                            },
                            overlapArea: Math.round(area),
                        });
                    }
                }
            }
            const allowedScrollable = (el) => {
                if (!el || !(el instanceof Element)) return false;
                if (el.closest('#sidebar')) return true;
                if (!(el instanceof HTMLElement)) return false;
                return Boolean(el.closest('.overflow-x-auto, .table-responsive'));
            };
            const overflowOffenders = Array.from(document.body.querySelectorAll('*'))
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
                textElementCount: items.length,
                overlaps: overlaps.slice(0, 10),
                overflowOffenders,
            };
        }"""
    )


def _core_todo_creation_desktop_text_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const selectors = {
                main: 'main[role="main"]',
                mainContent: '#mainContent',
                addForm: '#addForm',
                addFormForm: '#addForm form',
                addOptions: '#addFormOptions',
                optionControls: '#addFormOptions > div.flex',
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
            const directText = (el) => Array.from(el.childNodes)
                .filter((node) => node.nodeType === Node.TEXT_NODE)
                .map((node) => node.textContent.trim())
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();
            const readableName = (el) => {
                if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                    return el.value || el.placeholder || el.getAttribute('aria-label') || '';
                }
                if (el instanceof HTMLSelectElement) {
                    return el.getAttribute('aria-label') || el.options[el.selectedIndex]?.text || '';
                }
                return directText(el) || '';
            };
            const candidateSelector = [
                '#addForm h1',
                '#addForm h2',
                '#addForm h3',
                '#addForm p',
                '#addForm summary',
                '#addForm label',
                '#addForm button',
                '#addForm input',
                '#addForm textarea',
                '#addForm select',
                '#addForm .text-xs',
                '#addForm .text-sm',
                '#addForm .font-semibold',
                '#addForm .font-medium'
            ].join(',');
            const candidates = Array.from(document.querySelectorAll(candidateSelector))
                .filter((el) => el instanceof HTMLElement)
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    if (Number.parseFloat(style.opacity || '1') <= 0.01) return false;
                    const text = readableName(el);
                    if (!text) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 1 && rect.height > 1;
                });
            const items = [];
            candidates.forEach((el, index) => {
                const text = readableName(el).slice(0, 80);
                Array.from(el.getClientRects()).forEach((rect, rectIndex) => {
                    if (rect.width <= 1 || rect.height <= 1) return;
                    items.push({
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
                    });
                });
            });
            const overlaps = [];
            for (let i = 0; i < items.length; i += 1) {
                for (let j = i + 1; j < items.length; j += 1) {
                    const a = items[i];
                    const b = items[j];
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
                                box: [
                                    Math.round(a.left), Math.round(a.top),
                                    Math.round(a.right), Math.round(a.bottom)
                                ],
                            },
                            second: {
                                tag: b.tag,
                                id: b.id,
                                className: b.className,
                                text: b.text,
                                box: [
                                    Math.round(b.left), Math.round(b.top),
                                    Math.round(b.right), Math.round(b.bottom)
                                ],
                            },
                            overlapArea: Math.round(area),
                        });
                    }
                }
            }
            const allowedScrollable = (el) => {
                if (!el || !(el instanceof Element)) return false;
                if (el.closest('#sidebar')) return true;
                if (!(el instanceof HTMLElement)) return false;
                return Boolean(el.closest('.overflow-x-auto, .table-responsive'));
            };
            const overflowOffenders = Array.from(document.body.querySelectorAll('*'))
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
                textElementCount: items.length,
                overlaps: overlaps.slice(0, 10),
                overflowOffenders,
            };
        }"""
    )


def _core_todo_edit_desktop_text_metrics(page, todo_id: int):
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
                subtaskSection: `#todo-${todoId} div.mt-3.pt-3`,
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
            const directText = (el) => Array.from(el.childNodes)
                .filter((node) => node.nodeType === Node.TEXT_NODE)
                .map((node) => node.textContent.trim())
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();
            const readableName = (el) => {
                if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                    return el.value || el.placeholder || el.getAttribute('aria-label') || '';
                }
                if (el instanceof HTMLSelectElement) {
                    return el.getAttribute('aria-label') || el.options[el.selectedIndex]?.text || '';
                }
                return directText(el) || '';
            };
            const candidateSelector = [
                `#todo-${todoId} h4`,
                `#todo-${todoId} h5`,
                `#todo-${todoId} label`,
                `#todo-${todoId} span`,
                `#todo-${todoId} a`,
                `#todo-${todoId} button`,
                `#todo-${todoId} input`,
                `#todo-${todoId} textarea`,
                `#todo-${todoId} select`,
                `#todo-${todoId} .text-xs`,
                `#todo-${todoId} .text-sm`,
                `#todo-${todoId} .font-bold`,
                `#todo-${todoId} .font-medium`,
                `#todo-${todoId} .font-semibold`
            ].join(',');
            const candidates = Array.from(document.querySelectorAll(candidateSelector))
                .filter((el) => el instanceof HTMLElement)
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    if (Number.parseFloat(style.opacity || '1') <= 0.01) return false;
                    const text = readableName(el);
                    if (!text) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 1 && rect.height > 1;
                });
            const items = [];
            candidates.forEach((el, index) => {
                const text = readableName(el).slice(0, 80);
                Array.from(el.getClientRects()).forEach((rect, rectIndex) => {
                    if (rect.width <= 1 || rect.height <= 1) return;
                    items.push({
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
                    });
                });
            });
            const overlaps = [];
            for (let i = 0; i < items.length; i += 1) {
                for (let j = i + 1; j < items.length; j += 1) {
                    const a = items[i];
                    const b = items[j];
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
                                box: [
                                    Math.round(a.left), Math.round(a.top),
                                    Math.round(a.right), Math.round(a.bottom)
                                ],
                            },
                            second: {
                                tag: b.tag,
                                id: b.id,
                                className: b.className,
                                text: b.text,
                                box: [
                                    Math.round(b.left), Math.round(b.top),
                                    Math.round(b.right), Math.round(b.bottom)
                                ],
                            },
                            overlapArea: Math.round(area),
                        });
                    }
                }
            }
            const allowedScrollable = (el) => {
                if (!el || !(el instanceof Element)) return false;
                if (el.closest('#sidebar')) return true;
                if (!(el instanceof HTMLElement)) return false;
                return Boolean(el.closest('.overflow-x-auto, .table-responsive'));
            };
            const overflowOffenders = Array.from(document.body.querySelectorAll('*'))
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
                textElementCount: items.length,
                overlaps: overlaps.slice(0, 10),
                overflowOffenders,
            };
        }""",
        todo_id,
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_list_desktop_1440_major_text_does_not_overlap(
    optional_chromium_browser, app_name, app, mod
):
    html_response, todo_id = run_async(
        _fetch_core_todo_html_with_visible_item(app_name, app, mod)
    )
    _assert_static_core_todo_text_contract(app_name, html_response, todo_id)

    if optional_chromium_browser is None:
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

    metrics = _core_todo_desktop_text_metrics(page)
    assert metrics["viewportWidth"] == 1440, (
        f"{app_name} /todos: wrong viewport: {metrics}"
    )
    assert metrics["viewportHeight"] == 900, (
        f"{app_name} /todos: wrong viewport: {metrics}"
    )
    assert metrics["textElementCount"] >= 18, (
        f"{app_name} /todos: core list text candidates were not rendered: {metrics}"
    )
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

    assert not metrics["overflowOffenders"], (
        f"{app_name} /todos: visible elements exceed 1440px viewport: {metrics}"
    )
    assert not metrics["overlaps"], (
        f"{app_name} /todos: major todo list text elements overlap at 1440x900: {metrics}"
    )
    assert not page_errors, f"{app_name} /todos: page errors: {page_errors}"

    page.close()
    context.close()


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_edit_save_screen_desktop_1440_major_text_does_not_overlap(
    optional_chromium_browser, app_name, app, mod
):
    list_html, edit_html, todo_id = run_async(
        _fetch_core_todo_edit_html_with_visible_item(app_name, app, mod)
    )
    _assert_static_core_todo_text_contract(app_name, list_html, todo_id)
    assert f'id="todo-{todo_id}"' in edit_html
    assert f'id="editTodoForm-{todo_id}"' in edit_html
    assert f'hx-put="/todos/{todo_id}"' in edit_html
    assert f'hx-indicator="#todo-edit-loading-{todo_id}"' in edit_html
    assert f'id="todo-edit-loading-{todo_id}"' in edit_html
    assert 'aria-label="할일 제목"' in edit_html
    assert 'aria-label="설명"' in edit_html
    assert 'aria-label="마감일"' in edit_html
    assert 'aria-label="우선순위"' in edit_html
    assert 'aria-label="알림 시간 선택"' in edit_html
    assert 'aria-label="할일 저장 중"' in edit_html
    assert "변경사항을 저장하는 중입니다" in edit_html
    assert "저장" in edit_html

    if optional_chromium_browser is None:
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

    metrics = _core_todo_edit_desktop_text_metrics(page, todo_id)
    assert metrics["viewportWidth"] == 1440, (
        f"{app_name} /todos/{todo_id}/edit: wrong viewport: {metrics}"
    )
    assert metrics["viewportHeight"] == 900, (
        f"{app_name} /todos/{todo_id}/edit: wrong viewport: {metrics}"
    )
    assert metrics["textElementCount"] >= 12, (
        f"{app_name} /todos/{todo_id}/edit: edit form text candidates were not rendered: {metrics}"
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

    assert not metrics["overflowOffenders"], (
        f"{app_name} /todos/{todo_id}/edit: visible elements exceed 1440px viewport: {metrics}"
    )
    assert not metrics["overlaps"], (
        f"{app_name} /todos/{todo_id}/edit: major edit/save form text elements overlap at 1440x900: {metrics}"
    )
    assert not page_errors, f"{app_name} /todos/{todo_id}/edit: page errors: {page_errors}"

    page.close()
    context.close()


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_creation_screen_desktop_1440_major_text_does_not_overlap(
    optional_chromium_browser, app_name, app, mod
):
    html_response, todo_id = run_async(
        _fetch_core_todo_html_with_visible_item(app_name, app, mod)
    )
    _assert_static_core_todo_text_contract(app_name, html_response, todo_id)
    assert 'id="addFormOptions"' in html_response
    assert 'action="/todos"' in html_response
    assert 'name="title"' in html_response
    assert 'aria-label="알림 시간 선택"' in html_response

    if optional_chromium_browser is None:
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

    metrics = _core_todo_creation_desktop_text_metrics(page)
    assert metrics["viewportWidth"] == 1440, (
        f"{app_name} /todos#new: wrong viewport: {metrics}"
    )
    assert metrics["viewportHeight"] == 900, (
        f"{app_name} /todos#new: wrong viewport: {metrics}"
    )
    assert metrics["textElementCount"] >= 8, (
        f"{app_name} /todos#new: creation form text candidates were not rendered: {metrics}"
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

    assert not metrics["overflowOffenders"], (
        f"{app_name} /todos#new: visible elements exceed 1440px viewport: {metrics}"
    )
    assert not metrics["overlaps"], (
        f"{app_name} /todos#new: major creation form text elements overlap at 1440x900: {metrics}"
    )
    assert not page_errors, f"{app_name} /todos#new: page errors: {page_errors}"

    page.close()
    context.close()
