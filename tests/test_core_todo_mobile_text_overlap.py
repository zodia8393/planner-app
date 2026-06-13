"""
Visual layout checks for the jm/my MVP core todo list screens at 390x844.

The app fixtures use isolated temporary databases, so the visible test item is
not written to production data. When Chromium is available, this renders /todos
and measures the major text boxes for overlap and container overflow.
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


MOBILE_VIEWPORT = {"width": 390, "height": 844}
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


def _insert_mobile_text_todo(mod, profile_id: int, app_name: str) -> int:
    title = f"{app_name} mobile layout verification {uuid4().hex[:10]}"
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
                "Mobile 390 text overlap smoke item with readable metadata.",
                1,
                "2026-06-12",
                '["mvp-mobile-text"]',
                3,
                max_order + 1,
            ),
        )
        todo_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO subtasks (todo_id, title, sort_order) VALUES (?, ?, ?)",
            (todo_id, "Check mobile text bounds", 1),
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
            profile_name = f"MobileText{uuid4().hex[:8]}"
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

        todo_id = _insert_mobile_text_todo(mod, profile_id, app_name)
        response = await client.get("/todos")
        assert response.status_code == 200, f"{app_name} /todos: {response.status_code}"
        assert f'id="todo-{todo_id}"' in response.text
        return response.text, todo_id


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
    return html.replace("</head>", f"<style>{css}</style></head>")


def _assert_static_mobile_text_contract(app_name: str, html: str, todo_id: int) -> None:
    app_css = _asset_text(app_name, "static/css/app.css")

    assert 'role="main"' in html
    assert 'id="mainContent"' in html
    assert 'id="todoPage"' in html
    assert 'aria-label="할일 목록"' in html
    assert 'id="todoList"' in html
    assert f'id="todo-{todo_id}"' in html
    assert "업무 관리" in html
    assert "목록 보기" in html
    assert "정렬/필터" in html
    assert "새 업무 제목" in html
    assert "Mobile 390 text overlap smoke item" in html

    assert "*, *::before, *::after { box-sizing: border-box; }" in app_css
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert ".truncate" in _asset_text(app_name, "static/tailwind.css")
    assert ".flex { min-width: 0; }" in app_css
    assert ".flex > * { min-width: 0; }" in app_css
    assert "@media (max-width: 640px)" in app_css


def _mobile_text_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const selectors = {
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
            const allowedScrollable = (el) => Boolean(el.closest('#sidebar, .overflow-x-auto, .table-responsive'));
            const nearestContainer = (el) => el.closest('.work-card, article, section, form, details, #mainContent, main');
            const candidateSelector = [
                '.common-app-header h2',
                '.common-app-header p',
                '.common-app-header .date-badge',
                '#mainContent h1',
                '#mainContent h2',
                '#mainContent h3',
                '#mainContent p',
                '#mainContent summary',
                '#mainContent label',
                '#mainContent button',
                '#mainContent input',
                '#mainContent textarea',
                '#mainContent select',
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
                    if (allowedScrollable(el)) return false;
                    const text = readableName(el);
                    if (!text) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 1 && rect.height > 1;
                });
            const items = [];
            candidates.forEach((el, index) => {
                const text = readableName(el).slice(0, 90);
                const container = nearestContainer(el);
                const containerRect = container ? container.getBoundingClientRect() : null;
                Array.from(el.getClientRects()).forEach((rect, rectIndex) => {
                    if (rect.width <= 1 || rect.height <= 1) return;
                    items.push({
                        el,
                        key: `${index}:${rectIndex}`,
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 140),
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
            const textOverflow = items
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
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                containers: Object.fromEntries(
                    Object.entries(selectors).map(([key, selector]) => [key, rectFor(selector)])
                ),
                textElementCount: items.length,
                overlaps: overlaps.slice(0, 10),
                textOverflow,
                overflowOffenders,
            };
        }"""
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_list_mobile_390_major_text_does_not_overlap_or_overflow(
    optional_chromium_browser, app_name, app, mod
):
    html_response, todo_id = run_async(
        _fetch_core_todo_html_with_visible_item(app_name, app, mod)
    )
    _assert_static_mobile_text_contract(app_name, html_response, todo_id)

    if optional_chromium_browser is None:
        return

    html = _inline_render_css(app_name, html_response)
    context = optional_chromium_browser.new_context(
        viewport=MOBILE_VIEWPORT,
        java_script_enabled=False,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda err, _e=page_errors: _e.append(str(err)))
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    metrics = _mobile_text_metrics(page)
    assert metrics["viewportWidth"] == MOBILE_VIEWPORT["width"], (
        f"{app_name} /todos: wrong mobile viewport: {metrics}"
    )
    assert metrics["textElementCount"] >= 18, (
        f"{app_name} /todos: core list text candidates were not rendered: {metrics}"
    )
    assert metrics["documentScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, (
        f"{app_name} /todos: document overflows 390px mobile viewport: {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, (
        f"{app_name} /todos: body overflows 390px mobile viewport: {metrics}"
    )

    for key, rect in metrics["containers"].items():
        assert rect, f"{app_name} /todos: missing {key}: {metrics}"
        assert rect["right"] <= MOBILE_VIEWPORT["width"] + 2, (
            f"{app_name} /todos: {key} exceeds 390px viewport: {metrics}"
        )
        assert not rect["hasHorizontalScroll"], (
            f"{app_name} /todos: {key} has internal horizontal scroll: {metrics}"
        )

    assert not metrics["overflowOffenders"], (
        f"{app_name} /todos: visible elements exceed 390px viewport: {metrics}"
    )
    assert not metrics["textOverflow"], (
        f"{app_name} /todos: major text exceeds its viewport/container at 390x844: {metrics}"
    )
    assert not metrics["overlaps"], (
        f"{app_name} /todos: major text elements overlap at 390x844: {metrics}"
    )
    page_errors = [err for err in page_errors if "localStorage" not in err]
    assert not page_errors, f"{app_name} /todos: page errors: {page_errors}"

    page.close()
    context.close()
