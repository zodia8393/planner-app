"""
Independent visual layout checks for the jm/my todo creation form at 390x844.

The app fixtures use isolated temporary databases. This test only renders the
MVP /todos creation surface and does not leave records in production data.
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


async def _fetch_core_todo_creation_html(app_name: str, app, mod) -> str:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        if app_name == "my":
            profile_name = f"CreationMobileText{uuid4().hex[:8]}"
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

        response = await client.get("/todos")
        assert response.status_code == 200, f"{app_name} /todos: {response.status_code}"
        return response.text


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


def _assert_static_creation_text_contract(app_name: str, html: str) -> None:
    app_css = _asset_text(app_name, "static/css/app.css")

    assert 'role="main"' in html
    assert 'id="mainContent"' in html
    assert 'id="todoPage"' in html
    assert 'id="addForm"' in html
    assert 'action="/todos"' in html
    assert 'hx-post="/todos"' in html
    assert 'aria-label="새 업무 제목"' in html
    assert 'placeholder="할 일 입력 (/오늘, /높음 등 슬래시 명령 지원)"' in html
    assert 'type="submit"' in html
    assert "추가" in html
    assert 'id="todo-create-loading"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert "할일을 추가하는 중입니다" in html
    assert 'id="addFormOptions"' in html
    assert "옵션 더보기" in html
    assert 'aria-label="마감일"' in html
    assert 'aria-label="우선순위"' in html
    assert 'aria-label="카테고리"' in html
    assert 'aria-label="반복 설정"' in html
    assert 'aria-label="에너지 레벨"' in html
    assert 'aria-label="태그"' in html
    assert 'aria-label="알림 시간 선택"' in html
    assert 'aria-label="설명"' in html

    assert "*, *::before, *::after { box-sizing: border-box; }" in app_css
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert "input, select, textarea { max-width: 100%; box-sizing: border-box; }" in app_css
    assert "form { max-width: 100%; }" in app_css
    assert ".flex { min-width: 0; }" in app_css
    assert ".flex > * { min-width: 0; }" in app_css
    assert "@media (max-width: 640px)" in app_css
    assert "#mainContent :where(.work-card > .flex, .work-card form.flex" in app_css
    assert "flex-wrap: wrap;" in app_css
    assert "#mainContent :where(.work-card input:not([type=\"checkbox\"]):not([type=\"radio\"]), .work-card select, .work-card textarea)" in app_css


def _creation_form_text_metrics(page):
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
                creationForm: '#addForm form',
                firstRow: '#addForm form > .flex:first-of-type',
                loadingState: '#todo-create-loading',
                options: '#addFormOptions',
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
            const readableName = (el) => {
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
            const nearestContainer = (el) => el.closest('#addFormOptions, #todo-create-loading, form, #addForm, #mainContent, main');
            const candidates = Array.from(document.querySelectorAll([
                '#addForm button',
                '#addForm input',
                '#addForm textarea',
                '#addForm select',
                '#addForm label',
                '#addForm summary',
                '#todo-create-loading',
                '#todo-create-loading span',
                '#addRrulePanel span',
                '#addRrulePanel label'
            ].join(',')))
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
            const overflowOffenders = Array.from(document.querySelectorAll('#addForm, #addForm *'))
                .filter((el) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return false;
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
            const addFormRect = document.querySelector('#addForm').getBoundingClientRect();
            const clippedButtons = Array.from(document.querySelectorAll('#addForm button, #addForm summary'))
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    if (rect.width <= 1 || rect.height <= 1) return false;
                    return rect.left < addFormRect.left - 2
                        || rect.right > addFormRect.right + 2
                        || rect.left < -2
                        || rect.right > viewportWidth + 2;
                })
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        label: el.getAttribute('aria-label')
                            || el.textContent.trim().replace(/\\s+/g, ' '),
                        left: Math.round(rect.left),
                        right: Math.round(rect.right),
                        containerLeft: Math.round(addFormRect.left),
                        containerRight: Math.round(addFormRect.right),
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
                clippedButtons,
            };
        }"""
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_todo_creation_mobile_390_text_does_not_overlap_or_overflow(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_core_todo_creation_html(app_name, app, mod))
    _assert_static_creation_text_contract(app_name, html_response)

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
    page.locator("#addFormOptions").evaluate("element => { element.open = true; }")
    page.wait_for_timeout(100)

    metrics = _creation_form_text_metrics(page)
    assert metrics["viewportWidth"] == MOBILE_VIEWPORT["width"], (
        f"{app_name} /todos add form: wrong mobile viewport: {metrics}"
    )
    assert metrics["textElementCount"] >= 9, (
        f"{app_name} /todos add form: creation text candidates were not rendered: {metrics}"
    )
    assert metrics["documentScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, (
        f"{app_name} /todos add form: document overflows 390px mobile viewport: {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, (
        f"{app_name} /todos add form: body overflows 390px mobile viewport: {metrics}"
    )

    for key, rect in metrics["containers"].items():
        assert rect, f"{app_name} /todos add form: missing {key}: {metrics}"
        assert rect["right"] <= MOBILE_VIEWPORT["width"] + 2, (
            f"{app_name} /todos add form: {key} exceeds 390px viewport: {metrics}"
        )
        assert not rect["hasHorizontalScroll"], (
            f"{app_name} /todos add form: {key} has internal horizontal scroll: {metrics}"
        )

    assert not metrics["overflowOffenders"], (
        f"{app_name} /todos add form: visible elements exceed 390px viewport: {metrics}"
    )
    assert not metrics["clippedButtons"], (
        f"{app_name} /todos add form: creation buttons are clipped at 390x844: {metrics}"
    )
    assert not metrics["textOverflow"], (
        f"{app_name} /todos add form: major text exceeds container at 390x844: {metrics}"
    )
    assert not metrics["overlaps"], (
        f"{app_name} /todos add form: major text elements overlap at 390x844: {metrics}"
    )
    page_errors = [err for err in page_errors if "localStorage" not in err]
    assert not page_errors, f"{app_name} /todos add form: page errors: {page_errors}"

    page.close()
    context.close()
