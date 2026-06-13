"""
Button containment checks for jm/my non-core planner screens.

This intentionally excludes the MVP core todo flow and uses the isolated test
apps from conftest.py, so no production database or user data is touched.
"""

import re
from html.parser import HTMLParser
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
    "/today",
    "/memos",
    "/worklogs",
    "/ddays",
    "/links",
    "/search",
    "/settings",
    "/categories",
    "/notices",
]

APP_CASES = [
    ("jm", jm_app, COMMON_NON_CORE_ROUTES),
    ("my", my_app, COMMON_NON_CORE_ROUTES + ["/files"]),
]


def _client_for_app(app_name: str, app) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    if app_name == "my":
        response = client.post(
            "/setup",
            data={"name": f"NonCoreButtons{uuid4().hex[:8]}"},
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
    return html.replace("</head>", f"<style>{'\n'.join(css_chunks)}</style></head>")


def _app_css(app_name: str) -> str:
    return (ROOT / app_name / "static" / "css" / "app.css").read_text(encoding="utf-8")


class ControlTagParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls = []
        self._main_depth = 0
        self._mobile_nav_depth = 0

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if tag == "main":
            self._main_depth += 1
        if tag == "nav" and attr_map.get("id") == "mobileTabBar":
            self._mobile_nav_depth += 1
        if tag in {"button", "a"} and (self._main_depth or self._mobile_nav_depth):
            self.controls.append({"tag": tag, "attrs": attr_map, "raw": self.get_starttag_text() or ""})

    def handle_endtag(self, tag):
        if tag == "main" and self._main_depth:
            self._main_depth -= 1
        if tag == "nav" and self._mobile_nav_depth:
            self._mobile_nav_depth -= 1


def _rendered_control_tags(html: str) -> list[dict]:
    parser = ControlTagParser()
    parser.feed(html)
    return parser.controls


@pytest.mark.parametrize("app_name,app,routes", APP_CASES)
def test_jm_my_non_core_button_containment_static_contract(app_name, app, routes):
    css = _app_css(app_name)

    assert "#mainContent :where(button, a" in css
    assert "max-width: 100%;" in css
    assert "white-space: normal;" in css
    assert "overflow-wrap: anywhere;" in css
    assert "#mobileTabBar .mobile-tab-item" in css
    assert "min-width: 3.5rem;" in css
    assert "min-height: 2.75rem;" in css

    checked = 0
    clipped_controls = []
    template_names = [
        "base.html",
        "today.html",
        "memos.html",
        "worklogs.html",
        "ddays.html",
        "links.html",
        "search.html",
        "settings.html",
        "categories.html",
        "notices.html",
    ]
    if app_name == "my":
        template_names.append("files.html")

    for template_name in template_names:
        html = (ROOT / app_name / "templates" / template_name).read_text(encoding="utf-8")
        for control in _rendered_control_tags(html):
            checked += 1
            classes = set(control["attrs"].get("class", "").split())
            if classes & {"truncate", "overflow-hidden"}:
                clipped_controls.append({"template": template_name, "tag": control["raw"][:180]})

    assert checked > 0, f"{app_name}: no non-core button controls were rendered"
    assert not clipped_controls, f"{app_name}: controls carry direct clipping classes: {clipped_controls}"


@pytest.fixture(scope="module")
def chromium_browser():
    if sync_playwright is None:
        pytest.skip("Playwright browser is unavailable: missing playwright.sync_api")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(timeout=5000)
        except PlaywrightError as exc:
            pytest.skip(f"Playwright browser is unavailable: {exc}")
        yield browser
        browser.close()


def _button_containment_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const controlSelector = [
                '#mainContent :is(button, a[href], [role="button"])',
                '#mobileTabBar :is(button, a[href], [role="button"])'
            ].join(',');
            const isVisible = (el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number.parseFloat(style.opacity || '1') > 0.01
                    && rect.width > 1
                    && rect.height > 1;
            };
            const clippedRect = (el, rect) => {
                let left = rect.left;
                let right = rect.right;
                let top = rect.top;
                let bottom = rect.bottom;
                let parent = el.parentElement;
                while (parent) {
                    const style = getComputedStyle(parent);
                    const overflow = `${style.overflow} ${style.overflowX} ${style.overflowY}`;
                    if (/(auto|scroll|hidden|clip)/.test(overflow)) {
                        const parentRect = parent.getBoundingClientRect();
                        left = Math.max(left, parentRect.left);
                        right = Math.min(right, parentRect.right);
                        top = Math.max(top, parentRect.top);
                        bottom = Math.min(bottom, parentRect.bottom);
                    }
                    parent = parent.parentElement;
                }
                left = Math.max(left, 0);
                right = Math.min(right, viewportWidth);
                top = Math.max(top, 0);
                bottom = Math.min(bottom, viewportHeight);
                if (right - left <= 1 || bottom - top <= 1) return null;
                return {left, right, top, bottom, width: right - left, height: bottom - top};
            };
            const labelFor = (el) => (
                el.getAttribute('aria-label') ||
                el.getAttribute('title') ||
                el.innerText ||
                el.textContent ||
                ''
            ).trim().replace(/\\s+/g, ' ');
            const describe = (el) => {
                const rect = el.getBoundingClientRect();
                const visibleRect = clippedRect(el, rect) || rect;
                const style = getComputedStyle(el);
                const childOverflow = Array.from(el.querySelectorAll('svg, img, span, strong, em, small'))
                    .filter((child) => {
                        const childStyle = getComputedStyle(child);
                        const childRect = child.getBoundingClientRect();
                        if (
                            childStyle.display === 'none' ||
                            childStyle.visibility === 'hidden' ||
                            childRect.width <= 0 ||
                            childRect.height <= 0
                        ) return false;
                        return childRect.left < visibleRect.left - 2
                            || childRect.right > visibleRect.right + 2
                            || childRect.top < visibleRect.top - 2
                            || childRect.bottom > visibleRect.bottom + 2;
                    })
                    .slice(0, 4)
                    .map((child) => ({
                        tag: child.tagName.toLowerCase(),
                        text: (child.innerText || child.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 60),
                        left: Math.round(child.getBoundingClientRect().left),
                        right: Math.round(child.getBoundingClientRect().right),
                        top: Math.round(child.getBoundingClientRect().top),
                        bottom: Math.round(child.getBoundingClientRect().bottom),
                    }));

                const clipsOwnContent = (
                    (style.overflowX !== 'visible' && el.scrollWidth > el.clientWidth + 2) ||
                    (style.overflowY !== 'visible' && el.scrollHeight > el.clientHeight + 2)
                );
                const outsideViewport = visibleRect.left < -2
                    || visibleRect.right > viewportWidth + 2
                    || visibleRect.top < -2
                    || visibleRect.bottom > viewportHeight + 2;

                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    href: el.getAttribute('href') || '',
                    role: el.getAttribute('role') || '',
                    label: labelFor(el).slice(0, 90),
                    className: String(el.className || '').slice(0, 120),
                    whiteSpace: style.whiteSpace,
                    overflowX: style.overflowX,
                    overflowY: style.overflowY,
                    width: Math.round(visibleRect.width),
                    height: Math.round(visibleRect.height),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    outsideViewport,
                    clipsOwnContent,
                    childOverflow,
                };
            };

            const checks = Array.from(document.querySelectorAll(controlSelector))
                .filter(isVisible)
                .filter((el) => clippedRect(el, el.getBoundingClientRect()))
                .filter((el) => !el.closest('#todoPage'));
            const failures = checks
                .map(describe)
                .filter((item) => item.outsideViewport || item.clipsOwnContent || item.childOverflow.length > 0);

            return {
                viewportWidth,
                viewportHeight,
                checkedCount: checks.length,
                failures,
            };
        }"""
    )


@pytest.mark.parametrize("app_name,app,routes", APP_CASES)
def test_jm_my_non_core_buttons_do_not_clip_text_or_icons(chromium_browser, app_name, app, routes):
    client = _client_for_app(app_name, app)

    for viewport in (DESKTOP_VIEWPORT, MOBILE_VIEWPORT):
        context = chromium_browser.new_context(viewport=viewport, java_script_enabled=False)
        for route in routes:
            response = client.get(route)
            if response.status_code == 404 or 300 <= response.status_code < 400:
                continue
            assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
            html = _inline_render_css(response.text, client)

            page = context.new_page()
            page.set_content(html, wait_until="domcontentloaded", timeout=10000)
            page.wait_for_timeout(100)
            metrics = _button_containment_metrics(page)

            assert metrics["checkedCount"] > 0, f"{app_name} {route}: no rendered button controls"
            assert not metrics["failures"], (
                f"{app_name} {route} at {viewport}: button text/icon clipping or overflow: {metrics}"
            )
            page.close()
        context.close()
