"""
Independent desktop visual-overlap checks for jm/my non-core planner screens.

This excludes the MVP dashboard/todo flow and renders isolated TestClient
responses with inline CSS, so no production database or user data is touched.
"""

import re
import subprocess
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import jm_app, my_app


try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:
    PlaywrightError = None
    sync_playwright = None


DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
ORIGIN = {"origin": "http://testserver", "host": "testserver"}

COMMON_NON_CORE_ROUTES = [
    "/calendar",
    "/today",
    "/memos",
    "/worklogs",
    "/habits",
    "/timetable",
    "/ddays",
    "/links",
    "/achievements",
    "/stats",
    "/review",
    "/search",
    "/settings",
    "/todo-templates",
    "/automations",
    "/categories",
    "/forms",
    "/notices",
    "/plans",
    "/audit-log",
]

APP_CASES = [
    ("jm", jm_app, COMMON_NON_CORE_ROUTES),
    ("my", my_app, COMMON_NON_CORE_ROUTES + ["/files"]),
]


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
def chromium_browser():
    if sync_playwright is None:
        pytest.skip("Playwright browser is unavailable: missing playwright.sync_api")
    if not _can_launch_chromium():
        pytest.skip("Playwright Chromium is unavailable in this environment")

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(timeout=5000)
        except PlaywrightError as exc:
            pytest.skip(f"Playwright browser is unavailable: {exc}")
        yield browser
        browser.close()


def _client_for_app(app_name: str, app) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    if app_name == "my":
        response = client.post(
            "/setup",
            data={"name": f"NonCoreDesktopVisual{uuid4().hex[:8]}"},
            headers=ORIGIN,
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.cookies.get("planner_profile")
    return client


def _inline_render_css(html: str, client: TestClient) -> str:
    css_chunks = []
    for path in ("/static/tailwind.css", "/static/css/app.css"):
        response = client.get(path)
        assert response.status_code == 200, path
        css_chunks.append(response.text)

    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r'<script\b[^>]*\bsrc="[^"]+"[^>]*></script>', "", html)
    inline_css = "<style>" + "\n".join(css_chunks) + "</style>"
    return html.replace("</head>", f"{inline_css}</head>")


def _desktop_visual_overlap_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const readableName = (el) => (
                el.getAttribute('aria-label') ||
                el.getAttribute('title') ||
                el.getAttribute('placeholder') ||
                el.innerText ||
                el.textContent ||
                el.getAttribute('name') ||
                ''
            ).trim().replace(/\\s+/g, ' ');
            const isVisible = (el) => {
                if (!(el instanceof HTMLElement)) return false;
                if (el.closest('#todoPage, #sidebar, [hidden], [aria-hidden="true"]')) return false;
                const style = getComputedStyle(el);
                if (
                    style.display === 'none' ||
                    style.visibility === 'hidden' ||
                    Number.parseFloat(style.opacity || '1') <= 0.01
                ) return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 1 && rect.height > 1;
            };
            const allowedScrollable = (el) => Boolean(
                el.closest('.overflow-x-auto, .table-responsive, .memo-content')
            );
            const sameControl = (a, b) => {
                const controlSelector = 'a[href], button, label, summary, [role="button"], [role="link"]';
                const ac = a.closest(controlSelector);
                const bc = b.closest(controlSelector);
                return ac && ac === bc;
            };
            const describe = (item) => ({
                tag: item.el.tagName.toLowerCase(),
                id: item.el.id || '',
                className: String(item.el.className || '').slice(0, 140),
                text: item.text.slice(0, 90),
                box: [
                    Math.round(item.left),
                    Math.round(item.top),
                    Math.round(item.right),
                    Math.round(item.bottom),
                ],
            });
            const selector = [
                '.common-app-header :is(h1,h2,h3,p,a[href],button,.date-badge)',
                '#mainContent :is(h1,h2,h3,h4,p,summary,label,button,a[href],input,textarea,select,[role="status"],[role="alert"],.work-card,details,form,table)'
            ].join(',');
            const candidates = Array.from(document.querySelectorAll(selector))
                .filter(isVisible)
                .filter((el) => !allowedScrollable(el));
            const items = [];

            candidates.forEach((el, index) => {
                const text = readableName(el);
                if (!text && !el.matches('input,textarea,select,form,table,.work-card,details')) return;
                Array.from(el.getClientRects()).forEach((rect, rectIndex) => {
                    if (rect.width <= 1 || rect.height <= 1) return;
                    if (rect.bottom < -1 || rect.top > viewportHeight + 1) return;
                    items.push({
                        el,
                        key: `${index}:${rectIndex}`,
                        text: text || el.tagName.toLowerCase(),
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
                    if (sameControl(a.el, b.el)) continue;

                    const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                    const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                    if (x <= 1 || y <= 1) continue;

                    const area = x * y;
                    const smaller = Math.min(a.width * a.height, b.width * b.height);
                    if (area > 8 && area / smaller > 0.05) {
                        overlaps.push({
                            first: describe(a),
                            second: describe(b),
                            overlapArea: Math.round(area),
                        });
                    }
                }
            }

            const viewportOffenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => {
                    if (!(el instanceof HTMLElement)) return false;
                    if (!isVisible(el) || allowedScrollable(el)) return false;
                    const rect = el.getBoundingClientRect();
                    if (rect.bottom < -1 || rect.top > viewportHeight + 1) return false;
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
                scrollY: Math.round(window.scrollY),
                viewportWidth,
                viewportHeight,
                documentScrollWidth: document.documentElement.scrollWidth,
                bodyScrollWidth: document.body.scrollWidth,
                checkedCount: items.length,
                overlaps: overlaps.slice(0, 10),
                viewportOffenders,
            };
        }"""
    )


def _desktop_visual_metrics_across_scroll(page):
    total_height = page.evaluate(
        "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
    )
    step = max(1, DESKTOP_VIEWPORT["height"] - 120)
    scroll_positions = list(range(0, max(1, total_height), step))
    final_position = max(0, total_height - DESKTOP_VIEWPORT["height"])
    if final_position not in scroll_positions:
        scroll_positions.append(final_position)

    metrics_by_scroll = []
    for scroll_y in scroll_positions[:12]:
        page.evaluate("(y) => window.scrollTo(0, y)", scroll_y)
        page.wait_for_timeout(50)
        metrics_by_scroll.append(_desktop_visual_overlap_metrics(page))

    return {
        "totalHeight": total_height,
        "scrollPositions": scroll_positions[:12],
        "metrics": metrics_by_scroll,
    }


@pytest.mark.parametrize("app_name,app,routes", APP_CASES)
def test_jm_my_non_core_desktop_routes_have_no_visual_element_overlap(
    chromium_browser, app_name, app, routes
):
    client = _client_for_app(app_name, app)
    context = chromium_browser.new_context(
        viewport=DESKTOP_VIEWPORT,
        java_script_enabled=False,
    )

    for route in routes:
        response = client.get(route)
        if response.status_code == 404 or 300 <= response.status_code < 400:
            continue
        assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
        html = _inline_render_css(response.text, client)

        page = context.new_page()
        page.set_content(html, wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(100)
        metrics = _desktop_visual_metrics_across_scroll(page)

        assert any(item["checkedCount"] > 0 for item in metrics["metrics"]), (
            f"{app_name} {route}: no visible desktop elements were checked: {metrics}"
        )
        for item in metrics["metrics"]:
            assert item["viewportWidth"] == DESKTOP_VIEWPORT["width"], (
                f"{app_name} {route}: wrong desktop viewport: {item}"
            )
            assert item["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
                f"{app_name} {route}: document overflows desktop viewport: {item}"
            )
            assert item["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
                f"{app_name} {route}: body overflows desktop viewport: {item}"
            )
            assert not item["viewportOffenders"], (
                f"{app_name} {route}: visible element exceeds desktop viewport: {item}"
            )
            assert not item["overlaps"], (
                f"{app_name} {route}: visible elements overlap at 1440x900: {item}"
            )
        page.close()

    context.close()
