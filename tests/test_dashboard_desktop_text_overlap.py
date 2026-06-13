"""
Desktop text overlap checks for the jm/my MVP dashboard screens.

The apps come from conftest.py with isolated temp databases, so this test does
not touch production data. When Chromium is available, it renders the dashboard
at 1440x900 and checks the major visible text elements for overlapping boxes.
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


def _clear_dashboard_data(mod, profile_id: int) -> None:
    with mod.get_db() as conn:
        for table in ("todos", "events", "memos", "work_logs"):
            conn.execute(f"DELETE FROM {table} WHERE profile_id=?", (profile_id,))


async def _fetch_dashboard_html(app_name: str, app, mod) -> str:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"DashboardDesktop{uuid4().hex[:8]}"
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

        _clear_dashboard_data(mod, profile_id)
        response = await client.get("/")
        assert response.status_code == 200, f"{app_name} /: status {response.status_code}"
        return response.text


def _app_css(app_name: str, relative_path: str) -> str:
    return (ROOT / app_name / relative_path).read_text(encoding="utf-8")


def _inline_render_css(app_name: str, html: str) -> str:
    css_chunks = [
        _app_css(app_name, "static/tailwind.css"),
        _app_css(app_name, "static/css/app.css"),
        _app_css(app_name, "static/css/dashboard-grid.css"),
    ]

    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r'<script\b[^>]*\bsrc="[^"]+"[^>]*></script>', "", html)
    inline_css = "<style>" + "\n".join(css_chunks) + "</style>"
    return html.replace("</head>", f"{inline_css}</head>")


def _assert_static_dashboard_desktop_contract(app_name: str, html: str) -> None:
    app_css = _app_css(app_name, "static/css/app.css")
    dashboard_css = _app_css(app_name, "static/css/dashboard-grid.css")

    assert 'role="main"' in html
    assert 'id="mainContent"' in html
    assert 'aria-label="빠른 작업"' in html
    assert 'id="dashboard-empty-state"' in html
    assert 'aria-labelledby="dashboard-empty-title"' in html
    assert 'id="dashboardGrid"' in html
    assert "대시보드" in html
    assert "오늘의 업무 현황" in html
    assert "할일 추가" in html
    assert "첫 할일 만들기" in html

    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "#mainContent {" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert "#dashboardGrid {\n    display: grid;" in dashboard_css
    assert "grid-template-columns: repeat(12, 1fr);" in dashboard_css
    assert ".dashboard-widget {" in dashboard_css
    assert "min-width: 0;" in dashboard_css
    assert "overflow: hidden;" in dashboard_css


def _dashboard_desktop_text_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const selectors = {
                header: '.common-app-header',
                main: 'main[role="main"]',
                mainContent: '#mainContent',
                quickActions: '.dashboard-quick-actions',
                emptyState: '#dashboard-empty-state',
                dashboardGrid: '#dashboardGrid',
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
                return directText(el) || el.getAttribute('aria-label') || '';
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
                '#mainContent label',
                '#mainContent button',
                '#mainContent input',
                '#mainContent textarea',
                '#mainContent select',
                '#mainContent .quick-command-title',
                '#mainContent .quick-command-desc',
                '#mainContent .empty-state-primary',
                '#dashboardGrid .text-xs',
                '#dashboardGrid .text-sm',
                '#dashboardGrid .font-bold',
                '#dashboardGrid .font-semibold',
                '#dashboardGrid .font-extrabold'
            ].join(',');
            const candidates = Array.from(document.querySelectorAll(candidateSelector))
                .filter((el) => el instanceof HTMLElement)
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
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


def _dashboard_desktop_button_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const controlSelector = [
                '.dashboard-quick-actions a',
                '#dashboard-empty-state :is(a[href], button, [role="button"])',
                '#quickAddForm button[type="submit"]'
            ].join(',');
            const containerFor = (el) => el.closest(
                '.dashboard-quick-actions, #dashboard-empty-state, .dashboard-widget, #dashboardGrid, #mainContent'
            );
            const box = (rect) => ({
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                right: Math.round(rect.right),
                bottom: Math.round(rect.bottom),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            });
            const readableName = (el) => (
                el.getAttribute('aria-label') ||
                el.innerText ||
                el.textContent ||
                el.getAttribute('title') ||
                ''
            ).replace(/\\s+/g, ' ').trim();
            const controls = Array.from(document.querySelectorAll(controlSelector))
                .filter((el) => el instanceof HTMLElement)
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        rect.width > 1 &&
                        rect.height > 1;
                })
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    const container = containerFor(el);
                    const containerRect = container?.getBoundingClientRect();
                    const clippedHorizontally =
                        el.scrollWidth > el.clientWidth + 2 ||
                        rect.left < -2 ||
                        rect.right > viewportWidth + 2 ||
                        (containerRect && (
                            rect.left < containerRect.left - 2 ||
                            rect.right > containerRect.right + 2
                        ));
                    const clippedVertically =
                        el.scrollHeight > el.clientHeight + 2 ||
                        (rect.top >= 0 && rect.top <= viewportHeight && rect.bottom > viewportHeight + 2) ||
                        (containerRect && (
                            rect.top < containerRect.top - 2 ||
                            rect.bottom > containerRect.bottom + 2
                        ));
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 140),
                        text: readableName(el).slice(0, 80),
                        href: el.getAttribute('href') || '',
                        box: box(rect),
                        scrollWidth: el.scrollWidth,
                        clientWidth: el.clientWidth,
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        container: container ? {
                            selector: container.id ? `#${container.id}` : (
                                container.className ? `.${String(container.className).split(/\\s+/)[0]}` : container.tagName.toLowerCase()
                            ),
                            box: box(containerRect),
                            scrollWidth: container.scrollWidth,
                            clientWidth: container.clientWidth,
                            hasHorizontalScroll: container.scrollWidth > container.clientWidth + 2,
                        } : null,
                        clippedHorizontally,
                        clippedVertically,
                    };
                });
            return {
                viewportWidth,
                viewportHeight,
                controlCount: controls.length,
                controls,
                clippedControls: controls.filter((control) =>
                    control.clippedHorizontally || control.clippedVertically
                ),
                scrollContainers: controls
                    .map((control) => control.container)
                    .filter(Boolean)
                    .filter((container, index, all) =>
                        all.findIndex((item) => item.selector === container.selector) === index
                    )
                    .filter((container) => container.hasHorizontalScroll),
            };
        }"""
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_desktop_1440_major_text_does_not_overlap(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    _assert_static_dashboard_desktop_contract(app_name, html_response)

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

    metrics = _dashboard_desktop_text_metrics(page)
    assert metrics["viewportWidth"] == 1440, f"{app_name} /: wrong viewport: {metrics}"
    assert metrics["viewportHeight"] == 900, f"{app_name} /: wrong viewport: {metrics}"
    assert metrics["textElementCount"] >= 12, (
        f"{app_name} /: dashboard text candidates were not rendered: {metrics}"
    )
    assert metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /: document overflows desktop viewport: {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /: body overflows desktop viewport: {metrics}"
    )

    for key, rect in metrics["containers"].items():
        assert rect, f"{app_name} /: missing {key}: {metrics}"
        assert rect["right"] <= DESKTOP_VIEWPORT["width"] + 2, (
            f"{app_name} /: {key} exceeds 1440px viewport: {metrics}"
        )
        assert not rect["hasHorizontalScroll"], (
            f"{app_name} /: {key} has internal horizontal scroll: {metrics}"
        )

    assert not metrics["overflowOffenders"], (
        f"{app_name} /: visible elements exceed 1440px viewport: {metrics}"
    )
    assert not metrics["overlaps"], (
        f"{app_name} /: major dashboard text elements overlap at 1440x900: {metrics}"
    )
    assert not page_errors, f"{app_name} /: page errors: {page_errors}"

    page.close()
    context.close()


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_desktop_1440_major_buttons_stay_inside_containers(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    _assert_static_dashboard_desktop_contract(app_name, html_response)
    assert 'class="dashboard-quick-actions' in html_response
    assert 'class="quick-command-card' in html_response
    assert 'id="quickAddForm"' in html_response
    assert 'type="submit" class="px-5 py-2.5 text-sm font-semibold rounded-xl btn-accent"' in (
        html_response
    )

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

    metrics = _dashboard_desktop_button_metrics(page)
    assert metrics["viewportWidth"] == 1440, f"{app_name} /: wrong viewport: {metrics}"
    assert metrics["viewportHeight"] == 900, f"{app_name} /: wrong viewport: {metrics}"
    assert metrics["controlCount"] >= 5, (
        f"{app_name} /: expected quick actions, empty CTA, and quick-add submit: {metrics}"
    )
    assert not metrics["scrollContainers"], (
        f"{app_name} /: dashboard button containers have horizontal scroll: {metrics}"
    )
    assert not metrics["clippedControls"], (
        f"{app_name} /: major dashboard buttons overflow or are clipped at 1440x900: {metrics}"
    )
    assert not page_errors, f"{app_name} /: page errors: {page_errors}"

    page.close()
    context.close()
