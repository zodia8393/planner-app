"""
Independent text overflow checks for jm/my non-core planner screens.

This excludes the MVP todo flow and uses the isolated app fixtures from
conftest.py, so no production database or user data is touched.
"""

import re
import subprocess
import sys
from pathlib import Path
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
MOBILE_VIEWPORT = {"width": 390, "height": 844}
ORIGIN = {"origin": "http://testserver", "host": "testserver"}
ROOT = Path(__file__).resolve().parents[1]

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


def _client_for_app(app_name: str, app) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    if app_name == "my":
        response = client.post(
            "/setup",
            data={"name": f"NonCoreText{uuid4().hex[:8]}"},
            headers=ORIGIN,
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.cookies.get("planner_profile")
    return client


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


def _assert_static_non_core_text_contract(app_name: str) -> None:
    app_css = _asset_text(app_name, "static/css/app.css")

    assert "non-core responsive containment guard" in app_css
    assert "#mainContent {" in app_css
    assert "min-width: 0;" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert "#mainContent :where(.work-card, details, section, article, form, table)" in app_css
    assert "#mainContent :where(.flex-1, .min-w-0, p, span, h1, h2, h3, h4, h5, h6)" in app_css
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css


def _major_text_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const mainContent = document.getElementById('mainContent');
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
                return directText(el) || el.getAttribute('aria-label') || el.getAttribute('title') || '';
            };
            const allowedScrollable = (el) => Boolean(
                el.closest('#sidebar, .overflow-x-auto, .table-responsive, .memo-content')
            );
            const nearestContainer = (el) => el.closest(
                '.work-card, details, section, article, form, header, nav, #mainContent, main'
            );
            const describe = (el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                const container = nearestContainer(el);
                const containerRect = container?.getBoundingClientRect();
                const text = readableName(el).slice(0, 90);
                const classes = String(el.className || '');
                const mayClampVertically = /line-clamp-/.test(classes);
                const ownHorizontalOverflow = el.scrollWidth > el.clientWidth + 2;
                const ownVerticalOverflow = !mayClampVertically &&
                    style.overflowY !== 'visible' &&
                    el.scrollHeight > el.clientHeight + 2;
                const outsideViewport = rect.left < -2 || rect.right > viewportWidth + 2;
                const outsideContainer = Boolean(containerRect && (
                    rect.left < containerRect.left - 2 ||
                    rect.right > containerRect.right + 2
                ));

                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    className: classes.slice(0, 140),
                    text,
                    box: [
                        Math.round(rect.left),
                        Math.round(rect.top),
                        Math.round(rect.right),
                        Math.round(rect.bottom),
                    ],
                    whiteSpace: style.whiteSpace,
                    overflowX: style.overflowX,
                    overflowY: style.overflowY,
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    ownHorizontalOverflow,
                    ownVerticalOverflow,
                    outsideViewport,
                    outsideContainer,
                };
            };
            const selector = [
                '.common-app-header h2',
                '.common-app-header p',
                '.common-app-header .date-badge',
                '#mainContent h1',
                '#mainContent h2',
                '#mainContent h3',
                '#mainContent h4',
                '#mainContent p',
                '#mainContent summary',
                '#mainContent label',
                '#mainContent legend',
                '#mainContent button',
                '#mainContent a[href]',
                '#mainContent input',
                '#mainContent textarea',
                '#mainContent select',
                '#mainContent [role="status"]',
                '#mainContent [role="alert"]'
            ].join(',');
            const candidates = Array.from(document.querySelectorAll(selector))
                .filter((el) => el instanceof HTMLElement)
                .filter((el) => {
                    if (el.closest('#todoPage')) return false;
                    if (allowedScrollable(el)) return false;
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    if (Number.parseFloat(style.opacity || '1') <= 0.01) return false;
                    const text = readableName(el);
                    if (!text) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 1 && rect.height > 1;
                });
            const visibleElementOffenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => {
                    if (!(el instanceof HTMLElement)) return false;
                    if (allowedScrollable(el)) return false;
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
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
            const failures = candidates
                .map(describe)
                .filter((item) =>
                    item.ownHorizontalOverflow ||
                    item.ownVerticalOverflow ||
                    item.outsideViewport ||
                    item.outsideContainer
                );

            return {
                viewportWidth,
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                hasMainContent: Boolean(mainContent),
                visibleTextLength: mainContent ? mainContent.innerText.trim().length : 0,
                candidateCount: candidates.length,
                failures: failures.slice(0, 12),
                visibleElementOffenders,
            };
        }"""
    )


@pytest.mark.parametrize("app_name,app,routes", APP_CASES)
def test_jm_my_non_core_major_text_wraps_without_clipping_or_overflow(
    optional_chromium_browser, app_name, app, routes
):
    """Non-core pages keep major text readable at desktop and mobile widths."""
    _assert_static_non_core_text_contract(app_name)

    if optional_chromium_browser is None:
        return

    client = _client_for_app(app_name, app)
    for viewport in (DESKTOP_VIEWPORT, MOBILE_VIEWPORT):
        context = optional_chromium_browser.new_context(
            viewport=viewport, java_script_enabled=False
        )
        for route in routes:
            response = client.get(route)
            if response.status_code == 404 or 300 <= response.status_code < 400:
                continue
            assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
            html = _inline_render_css(app_name, response.text)

            page = context.new_page()
            page.set_content(html, wait_until="domcontentloaded", timeout=10000)
            page.wait_for_timeout(100)
            metrics = _major_text_metrics(page)

            assert metrics["hasMainContent"], f"{app_name} {route}: missing main content"
            assert metrics["visibleTextLength"] > 0, f"{app_name} {route}: no visible text"
            assert metrics["candidateCount"] > 0, f"{app_name} {route}: no major text candidates"
            assert metrics["documentScrollWidth"] <= viewport["width"] + 2, (
                f"{app_name} {route} at {viewport}: document has horizontal overflow: {metrics}"
            )
            assert metrics["bodyScrollWidth"] <= viewport["width"] + 2, (
                f"{app_name} {route} at {viewport}: body has horizontal overflow: {metrics}"
            )
            assert not metrics["visibleElementOffenders"], (
                f"{app_name} {route} at {viewport}: visible elements exceed viewport: {metrics}"
            )
            assert not metrics["failures"], (
                f"{app_name} {route} at {viewport}: major text is clipped or overflowing: {metrics}"
            )
            page.close()
        context.close()
