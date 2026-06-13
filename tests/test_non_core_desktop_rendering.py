"""
Responsive rendering checks for jm/my non-core planner screens.

These tests use the already-isolated apps from conftest.py, so no production
data or user database is touched.
"""

import re
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import httpx
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


def test_jm_non_core_routes_have_mobile_overflow_guard_contract():
    """Keep jm non-core pages guarded even when Playwright is unavailable."""
    css = (ROOT / "jm" / "static" / "css" / "app.css").read_text(encoding="utf-8")

    assert "JM non-core responsive containment guard" in css
    assert "#mainContent" in css
    assert "overflow-wrap: anywhere" in css
    assert "white-space: normal" in css
    assert "@media (max-width: 640px)" in css
    assert ".settings-page form.flex" in css
    assert "#mainContent :where(button, a" in css
    assert "#mainContent :where(.work-card" in css
    assert "*:focus-visible" in css
    assert "input:focus-visible" in css
    assert "#mainContent :where(a[href], button, summary" in css
    assert "#mobileTabBar :where(a[href], button" in css


def test_my_non_core_routes_have_mobile_overflow_guard_contract():
    """Keep my non-core pages guarded even when Playwright is unavailable."""
    css = (ROOT / "my" / "static" / "css" / "app.css").read_text(encoding="utf-8")

    assert "MY non-core responsive containment guard" in css
    assert "#mainContent" in css
    assert "overflow-wrap: anywhere" in css
    assert "white-space: normal" in css
    assert "@media (max-width: 640px)" in css
    assert ".settings-page form.flex" in css
    assert "#mainContent :where(button, a" in css
    assert "#mainContent :where(.work-card" in css
    assert "*:focus-visible" in css
    assert "input:focus-visible" in css
    assert "#mainContent :where(a[href], button, summary" in css
    assert "#mobileTabBar :where(a[href], button" in css


@pytest.mark.parametrize("app_name", ["jm", "my"])
def test_jm_my_global_footer_has_responsive_layout_contract(app_name: str):
    """Keep the shared mobile footer stable even when Playwright is unavailable."""
    base = (ROOT / app_name / "templates" / "base.html").read_text(encoding="utf-8")
    css = (ROOT / app_name / "static" / "css" / "app.css").read_text(encoding="utf-8")

    assert '<nav id="mobileTabBar"' in base
    assert 'class="mobile-tab-bar lg:hidden safe-bottom"' in base
    assert 'aria-label="모바일 탭 내비게이션"' in base
    assert 'hx-target="#mainContent"' in base
    assert "mobile-pad-bottom" in base
    assert base.count('class="mobile-tab-item') == 5
    assert ".mobile-tab-bar {" in css
    assert "position: fixed;" in css
    assert "bottom: 0; left: 0; right: 0;" in css
    assert "padding-bottom: env(safe-area-inset-bottom, 0px);" in css
    assert ".mobile-tab-bar > div" in css
    assert "calc(0.25rem + env(safe-area-inset-bottom, 0px))" in css
    assert ".mobile-tab-item {" in css
    assert "min-width: 3.5rem;" in css
    assert "min-height: 2.75rem;" in css
    assert ".mobile-pad-bottom" in css
    assert "padding-bottom: calc(var(--m-tabbar-height) + env(safe-area-inset-bottom, 0px) + 2rem)" in css
    assert "@media (min-width: 1024px)" in css
    assert ".mobile-tab-bar { display: none !important; }" in css


def _client_for_app(app_name: str, app) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    if app_name == "my":
        response = client.post(
            "/setup",
            data={"name": f"NonCoreRender{uuid4().hex[:8]}"},
            headers=ORIGIN,
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.cookies.get("planner_profile")
    return client


def _accessible_text(node) -> str:
    return " ".join(node.split())


def _accessible_name(control: dict, labels_by_for: dict[str, str]) -> str:
    attrs = control["attrs"]
    names = []
    for attr in ("aria-label", "title", "placeholder"):
        value = attrs.get(attr)
        if value and str(value).strip():
            names.append(str(value).strip())

    labelledby = attrs.get("aria-labelledby")
    if labelledby:
        for label_id in labelledby.split():
            label = labels_by_for.get(f"#{label_id}")
            if label:
                names.append(label)

    control_id = attrs.get("id")
    if control_id:
        label = labels_by_for.get(control_id)
        if label:
            names.append(label)

    if control["tag"] == "input" and attrs.get("type") in {"submit", "button", "reset"}:
        names.append(attrs.get("value", ""))

    names.append(_accessible_text(" ".join(control["text"])))
    names.extend(control["img_alts"])

    return _accessible_text(" ".join(name for name in names if name))


def _is_static_a11y_control_ignored(control: dict) -> bool:
    attrs = control["attrs"]
    if attrs.get("type") == "hidden":
        return True
    if "disabled" in attrs:
        return True
    if attrs.get("aria-hidden") == "true":
        return True

    classes = set(attrs.get("class", "").split())
    return bool({"hidden", "sr-only"} & classes)


def _describe_control(control: dict) -> dict:
    attrs = control["attrs"]
    return {
        "tag": control["tag"],
        "id": attrs.get("id", ""),
        "type": attrs.get("type", ""),
        "role": attrs.get("role", ""),
        "href": attrs.get("href", ""),
        "name": attrs.get("name", ""),
        "class": attrs.get("class", "")[:120],
        "html": control["html"][:180].replace("\n", " "),
    }


class AccessibleControlParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls = []
        self.labels_by_for = {}
        self._control_stack = []
        self._label_stack = []

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        raw = self.get_starttag_text() or ""

        if tag == "img" and attr_map.get("alt"):
            for control in self._control_stack:
                control["img_alts"].append(attr_map["alt"])

        if tag == "label":
            self._label_stack.append({"for": attr_map.get("for"), "text": []})

        if self._is_control(tag, attr_map):
            control = {
                "tag": tag,
                "attrs": attr_map,
                "text": [],
                "img_alts": [],
                "html": raw,
            }
            self.controls.append(control)
            if tag not in {"input"}:
                self._control_stack.append(control)

    def handle_data(self, data):
        if not data.strip():
            return
        for control in self._control_stack:
            control["text"].append(data)
        if self._label_stack:
            self._label_stack[-1]["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "label" and self._label_stack:
            label = self._label_stack.pop()
            label_for = label["for"]
            if label_for:
                self.labels_by_for[label_for] = _accessible_text(" ".join(label["text"]))

        if self._control_stack and self._control_stack[-1]["tag"] == tag:
            self._control_stack.pop()

    @staticmethod
    def _is_control(tag, attrs):
        if tag == "a" and attrs.get("href"):
            return True
        if tag in {"button", "select", "textarea"}:
            return True
        if tag == "input" and attrs.get("type") != "hidden":
            return True
        return attrs.get("role") in {"button", "link"}


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


def _inline_render_dashboard_css(html: str, client: TestClient) -> str:
    css_chunks = []
    for path in (
        "/static/tailwind.css",
        "/static/css/app.css",
        "/static/css/dashboard-grid.css",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        css_chunks.append(response.text)

    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r'<script\b[^>]*\bsrc="[^"]+"[^>]*></script>', "", html)
    inline_css = "<style>" + "\n".join(css_chunks) + "</style>"
    return html.replace("</head>", f"{inline_css}</head>")


def _dashboard_desktop_overflow_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const main = document.querySelector('main[role="main"]');
            const mainContent = document.getElementById('mainContent');
            const dashboardGrid = document.getElementById('dashboardGrid');
            const rectFor = (el) => {
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                };
            };
            const offenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return false;
                    if (el.closest('.overflow-x-auto, .table-responsive')) return false;
                    return rect.left < -2 || rect.right > viewportWidth + 2;
                })
                .slice(0, 5)
                .map((el) => ({
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    className: String(el.className || '').slice(0, 120),
                    left: Math.round(el.getBoundingClientRect().left),
                    right: Math.round(el.getBoundingClientRect().right),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                }));

            return {
                viewportWidth,
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                main: rectFor(main),
                mainContent: rectFor(mainContent),
                dashboardGrid: rectFor(dashboardGrid),
                hasDashboardGrid: Boolean(dashboardGrid),
                mainContentOverflows: Boolean(
                    mainContent && mainContent.scrollWidth > mainContent.clientWidth + 2
                ),
                dashboardGridOverflows: Boolean(
                    dashboardGrid && dashboardGrid.scrollWidth > dashboardGrid.clientWidth + 2
                ),
                visibleTextLength: mainContent ? mainContent.innerText.trim().length : 0,
                offenders,
            };
        }"""
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("app_name,app,routes", APP_CASES)
async def test_jm_my_non_core_routes_have_accessible_names_for_controls(app_name, app, routes):
    """Rendered non-core pages keep labels/names even without browser tooling."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        if app_name == "my":
            response = await client.post(
                "/setup",
                data={"name": f"NonCoreA11y{uuid4().hex[:8]}"},
                headers=ORIGIN,
                follow_redirects=False,
            )
            assert response.status_code == 303

        for route in routes:
            response = await client.get(route)
            if response.status_code == 404 or 300 <= response.status_code < 400:
                continue
            assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
            parser = AccessibleControlParser()
            parser.feed(response.text)
            controls = []

            for control in parser.controls:
                if _is_static_a11y_control_ignored(control):
                    continue
                if not _accessible_name(control, parser.labels_by_for):
                    controls.append(_describe_control(control))

            assert not controls, f"{app_name} {route}: controls without accessible names: {controls}"


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


def _desktop_layout_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const main = document.querySelector('main[role="main"]');
            const mainContent = document.getElementById('mainContent');
            const sidebar = document.getElementById('sidebar');
            const mobileTabs = document.getElementById('mobileTabBar');
            const mainRect = main ? main.getBoundingClientRect() : null;
            const contentRect = mainContent ? mainContent.getBoundingClientRect() : null;
            const sidebarRect = sidebar ? sidebar.getBoundingClientRect() : null;
            const mobileTabStyle = mobileTabs ? getComputedStyle(mobileTabs) : null;
            const visibleText = mainContent ? mainContent.innerText.trim() : '';

            return {
                viewportWidth,
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                hasMain: Boolean(main),
                hasMainContent: Boolean(mainContent),
                mainVisible: Boolean(mainRect && mainRect.width > 900 && mainRect.height > 300),
                contentVisible: Boolean(contentRect && contentRect.width > 700 && contentRect.height > 120),
                sidebarVisible: Boolean(sidebarRect && sidebarRect.width >= 240 && sidebarRect.height >= 800),
                mainAlignedAfterSidebar: Boolean(mainRect && sidebarRect && mainRect.left >= sidebarRect.right - 1),
                mobileTabsHidden: !mobileTabStyle || mobileTabStyle.display === 'none' || mobileTabStyle.visibility === 'hidden',
                visibleTextLength: visibleText.length,
            };
        }"""
    )


def _global_footer_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const doc = document.documentElement;
            const mobileTabs = document.getElementById('mobileTabBar');
            const rect = mobileTabs ? mobileTabs.getBoundingClientRect() : null;
            const style = mobileTabs ? getComputedStyle(mobileTabs) : null;
            const items = mobileTabs
                ? Array.from(mobileTabs.querySelectorAll(':scope > div > :is(a[href], button)'))
                : [];
            const itemRects = items.map((el) => el.getBoundingClientRect());
            const visible = Boolean(
                rect &&
                style &&
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                rect.width > 0 &&
                rect.height > 0
            );
            const hidden = !style || style.display === 'none' || style.visibility === 'hidden' ||
                !rect || rect.width === 0 || rect.height === 0;
            const offenders = itemRects
                .map((itemRect, index) => ({index, left: itemRect.left, right: itemRect.right}))
                .filter((itemRect) => itemRect.left < -1 || itemRect.right > viewportWidth + 1);

            return {
                viewportWidth,
                viewportHeight,
                documentScrollWidth: doc.scrollWidth,
                exists: Boolean(mobileTabs),
                visible,
                hidden,
                pinnedToBottom: Boolean(rect && Math.abs(rect.bottom - viewportHeight) <= 2),
                insideViewport: Boolean(
                    rect &&
                    rect.left >= -1 &&
                    rect.right <= viewportWidth + 1 &&
                    rect.bottom <= viewportHeight + 1 &&
                    rect.top >= 0
                ),
                itemCount: items.length,
                minItemWidth: itemRects.length ? Math.min(...itemRects.map((itemRect) => itemRect.width)) : 0,
                minItemHeight: itemRects.length ? Math.min(...itemRects.map((itemRect) => itemRect.height)) : 0,
                offenders,
            };
        }"""
    )


def _mobile_layout_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const doc = document.documentElement;
            const body = document.body;
            const main = document.querySelector('main[role="main"]');
            const mainContent = document.getElementById('mainContent');
            const sidebar = document.getElementById('sidebar');
            const mobileTabs = document.getElementById('mobileTabBar');
            const mainRect = main ? main.getBoundingClientRect() : null;
            const contentRect = mainContent ? mainContent.getBoundingClientRect() : null;
            const sidebarRect = sidebar ? sidebar.getBoundingClientRect() : null;
            const mobileTabsRect = mobileTabs ? mobileTabs.getBoundingClientRect() : null;
            const mobileTabStyle = mobileTabs ? getComputedStyle(mobileTabs) : null;
            const sidebarStyle = sidebar ? getComputedStyle(sidebar) : null;
            const visibleText = mainContent ? mainContent.innerText.trim() : '';
            const allowedScrollable = (el) => {
                if (!el || !(el instanceof Element)) return false;
                if (el.closest('#sidebar')) return true;
                if (!(el instanceof HTMLElement)) return false;
                return Boolean(el.closest('.overflow-x-auto, .table-responsive, .memo-content'));
            };
            const offenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return false;
                    if (allowedScrollable(el)) return false;
                    return rect.left < -2 || rect.right > viewportWidth + 2;
                })
                .slice(0, 5)
                .map((el) => ({
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    className: String(el.className || '').slice(0, 120),
                    left: Math.round(el.getBoundingClientRect().left),
                    right: Math.round(el.getBoundingClientRect().right),
                }));

            return {
                viewportWidth,
                documentScrollWidth: doc.scrollWidth,
                bodyScrollWidth: body.scrollWidth,
                hasMain: Boolean(main),
                hasMainContent: Boolean(mainContent),
                mainVisible: Boolean(mainRect && mainRect.width >= viewportWidth - 2 && mainRect.height > 300),
                contentVisible: Boolean(contentRect && contentRect.width >= viewportWidth - 32 && contentRect.height > 120),
                sidebarOffCanvas: Boolean(
                    sidebarRect &&
                    sidebarStyle &&
                    (sidebarStyle.transform !== 'none' || sidebarRect.right <= 4)
                ),
                mobileTabsVisible: Boolean(
                    mobileTabsRect &&
                    mobileTabStyle &&
                    mobileTabStyle.display !== 'none' &&
                    mobileTabStyle.visibility !== 'hidden' &&
                    mobileTabsRect.width >= viewportWidth - 2 &&
                    mobileTabsRect.height >= 48
                ),
                mobileTabsPinnedToBottom: Boolean(
                    mobileTabsRect &&
                    Math.abs(mobileTabsRect.bottom - window.innerHeight) <= 2
                ),
                visibleTextLength: visibleText.length,
                offenders,
            };
        }"""
    )


def _common_layout_overlap_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const rectFor = (selector) => {
                const el = document.querySelector(selector);
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                if (
                    rect.width <= 0 ||
                    rect.height <= 0 ||
                    style.display === 'none' ||
                    style.visibility === 'hidden'
                ) return null;
                return {
                    selector,
                    left: rect.left,
                    right: rect.right,
                    top: rect.top,
                    bottom: rect.bottom,
                    width: rect.width,
                    height: rect.height,
                };
            };
            const overlaps = (a, b) => Boolean(
                a && b &&
                a.left < b.right - 1 &&
                a.right > b.left + 1 &&
                a.top < b.bottom - 1 &&
                a.bottom > b.top + 1
            );
            const inViewport = (rect) => Boolean(
                rect &&
                rect.left >= -1 &&
                rect.right <= viewportWidth + 1 &&
                rect.top >= -1 &&
                rect.bottom <= viewportHeight + 1
            );

            const offlineBanner = document.getElementById('offlineBanner');
            if (offlineBanner) {
                offlineBanner.classList.remove('hidden');
                offlineBanner.setAttribute('data-state', 'reconnecting');
                const text = document.getElementById('offlineBannerText');
                if (text) text.textContent = '연결을 다시 확인하는 중입니다';
            }
            const toastContainer = document.getElementById('toastContainer');
            if (toastContainer) {
                toastContainer.innerHTML = '<div class="toast toast-info" role="status">저장 상태를 확인했습니다</div>';
            }

            const header = rectFor('.common-app-header');
            const headerTitle = rectFor('.common-app-title-group');
            const headerActions = rectFor('.common-app-header-actions');
            const syncBanner = rectFor('#offlineBanner');
            const toast = rectFor('#toastContainer .toast');
            const mobileTabs = rectFor('#mobileTabBar');
            const sidebar = rectFor('#sidebar');

            return {
                viewportWidth,
                headerInViewport: inViewport(header),
                headerTitleInViewport: inViewport(headerTitle),
                headerActionsInViewport: inViewport(headerActions),
                syncBannerInViewport: inViewport(syncBanner),
                toastInViewport: inViewport(toast),
                mobileTabsInViewport: !mobileTabs || inViewport(mobileTabs),
                headerTitleOverlapsActions: overlaps(headerTitle, headerActions),
                syncBannerOverlapsHeaderActions: overlaps(syncBanner, headerActions),
                syncBannerOverlapsToast: overlaps(syncBanner, toast),
                toastOverlapsMobileTabs: overlaps(toast, mobileTabs),
                mobileTabsOverlapsHeader: overlaps(mobileTabs, header),
                sidebarOverlapsHeader: overlaps(sidebar, header),
                rects: {header, headerTitle, headerActions, syncBanner, toast, mobileTabs, sidebar},
            };
        }"""
    )


def _keyboard_accessibility_metrics(page):
    return page.evaluate(
        """() => {
            const isHidden = (el) => {
                if (!el || !(el instanceof HTMLElement)) return true;
                if (el.closest('[hidden], [aria-hidden="true"], .hidden')) return true;
                const style = getComputedStyle(el);
                if (
                    style.display === 'none' ||
                    style.visibility === 'hidden' ||
                    style.pointerEvents === 'none'
                ) return true;
                const rect = el.getBoundingClientRect();
                return rect.width <= 0 || rect.height <= 0;
            };
            const labelFor = (el) => {
                const id = el.getAttribute('id');
                const explicitLabel = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
                return (
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') ||
                    el.getAttribute('placeholder') ||
                    (explicitLabel && explicitLabel.innerText) ||
                    el.innerText ||
                    el.textContent ||
                    el.getAttribute('name') ||
                    ''
                ).trim().replace(/\\s+/g, ' ');
            };
            const describe = (el) => ({
                tag: el.tagName.toLowerCase(),
                id: el.id || '',
                role: el.getAttribute('role') || '',
                type: el.getAttribute('type') || '',
                href: el.getAttribute('href') || '',
                name: el.getAttribute('name') || '',
                label: labelFor(el).slice(0, 80),
                tabindex: el.getAttribute('tabindex') || '',
                className: String(el.className || '').slice(0, 100),
            });
            const nativeSelector = [
                'a[href]',
                'button',
                'input:not([type="hidden"])',
                'select',
                'textarea',
                'summary',
                '[tabindex]:not([tabindex="-1"])',
                '[role="button"]',
                '[role="link"]'
            ].join(',');
            const commandSelector = [
                '[onclick]',
                '[data-action]',
                '[hx-get]',
                '[hx-post]',
                '[hx-put]',
                '[hx-delete]',
                '[role="button"]',
                '[role="link"]'
            ].join(',');
            const visibleFocusable = Array.from(document.querySelectorAll(nativeSelector))
                .filter((el) => !isHidden(el) && !el.disabled && el.tabIndex >= 0);
            const visibleCommands = Array.from(document.querySelectorAll(commandSelector))
                .filter((el) => !isHidden(el) && !el.disabled);
            const notKeyboardReachable = visibleCommands
                .filter((el) => !el.matches(nativeSelector) || el.tabIndex < 0)
                .map(describe);
            const unlabeled = visibleFocusable
                .filter((el) => {
                    const tag = el.tagName.toLowerCase();
                    if (!['a', 'button', 'input', 'select', 'textarea'].includes(tag)) return false;
                    return !labelFor(el);
                })
                .map(describe);

            return {
                focusableCount: visibleFocusable.length,
                mainFocusableCount: visibleFocusable.filter((el) => el.closest('#mainContent')).length,
                mainCommandCount: visibleCommands.filter((el) => el.closest('#mainContent')).length,
                visibleFocusable: visibleFocusable.map(describe),
                mainFocusable: visibleFocusable.filter((el) => el.closest('#mainContent')).map(describe),
                mobileFocusable: visibleFocusable.filter((el) => el.closest('#mobileTabBar')).map(describe),
                notKeyboardReachable,
                unlabeled,
            };
        }"""
    )


def _tab_sequence(page, steps: int):
    sequence = []
    for _ in range(steps):
        page.keyboard.press("Tab")
        focused = page.evaluate(
            """() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                const label = (
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') ||
                    el.getAttribute('placeholder') ||
                    el.innerText ||
                    el.textContent ||
                    el.getAttribute('name') ||
                    ''
                ).trim().replace(/\\s+/g, ' ');
                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    href: el.getAttribute('href') || '',
                    name: el.getAttribute('name') || '',
                    label: label.slice(0, 80),
                    inMain: Boolean(el.closest('#mainContent')),
                    inMobileTabs: Boolean(el.closest('#mobileTabBar')),
                };
            }"""
        )
        if focused:
            sequence.append(focused)
    return sequence


def _focused_indicator_after_tab_until(page, target_expression: str, steps: int):
    for _ in range(steps):
        page.keyboard.press("Tab")
        indicator = page.evaluate(
            """(targetExpression) => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                if (!Function(`return (${targetExpression});`)()) return null;

                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                const outlineWidth = Number.parseFloat(style.outlineWidth) || 0;
                const outlineVisible = (
                    outlineWidth >= 2 &&
                    style.outlineStyle !== 'none' &&
                    style.outlineColor !== 'rgba(0, 0, 0, 0)' &&
                    style.outlineColor !== 'transparent'
                );
                const shadowVisible = (
                    style.boxShadow !== 'none' &&
                    !style.boxShadow.includes('0px 0px 0px 0px')
                );
                const label = (
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') ||
                    el.getAttribute('placeholder') ||
                    el.innerText ||
                    el.textContent ||
                    el.getAttribute('name') ||
                    ''
                ).trim().replace(/\\s+/g, ' ');

                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    href: el.getAttribute('href') || '',
                    name: el.getAttribute('name') || '',
                    label: label.slice(0, 80),
                    className: String(el.className || '').slice(0, 120),
                    outlineWidth,
                    outlineStyle: style.outlineStyle,
                    outlineColor: style.outlineColor,
                    boxShadow: style.boxShadow,
                    visibleRect: rect.width > 0 && rect.height > 0,
                    inViewport: rect.bottom > 0 && rect.top < window.innerHeight,
                    hasVisibleFocusIndicator: outlineVisible || shadowVisible,
                };
            }""",
            target_expression,
        )
        if indicator:
            return indicator
    return None


COMMON_LAYOUT_ROUTES = ["/", "/todos"]


@pytest.mark.parametrize("app_name,app", [("jm", jm_app), ("my", my_app)])
def test_jm_my_common_header_navigation_status_do_not_overlap(chromium_browser, app_name, app):
    client = _client_for_app(app_name, app)

    for viewport in (DESKTOP_VIEWPORT, MOBILE_VIEWPORT):
        context = chromium_browser.new_context(viewport=viewport, java_script_enabled=False)

        for route in COMMON_LAYOUT_ROUTES:
            response = client.get(route)
            assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
            html = _inline_render_css(response.text, client)

            page = context.new_page()
            page.set_content(html, wait_until="domcontentloaded", timeout=10000)
            page.wait_for_timeout(100)

            metrics = _common_layout_overlap_metrics(page)
            assert metrics["headerInViewport"], f"{app_name} {route}: header outside viewport: {metrics}"
            assert metrics["headerTitleInViewport"], f"{app_name} {route}: header title outside viewport: {metrics}"
            assert metrics["headerActionsInViewport"], f"{app_name} {route}: header actions outside viewport: {metrics}"
            assert metrics["syncBannerInViewport"], f"{app_name} {route}: sync banner outside viewport: {metrics}"
            assert metrics["toastInViewport"], f"{app_name} {route}: toast outside viewport: {metrics}"
            assert metrics["mobileTabsInViewport"], f"{app_name} {route}: mobile tabs outside viewport: {metrics}"
            assert not metrics["headerTitleOverlapsActions"], (
                f"{app_name} {route}: header title overlaps actions at {viewport}: {metrics}"
            )
            assert not metrics["syncBannerOverlapsHeaderActions"], (
                f"{app_name} {route}: sync banner overlaps header actions at {viewport}: {metrics}"
            )
            assert not metrics["syncBannerOverlapsToast"], (
                f"{app_name} {route}: sync banner overlaps toast at {viewport}: {metrics}"
            )
            assert not metrics["toastOverlapsMobileTabs"], (
                f"{app_name} {route}: toast overlaps mobile navigation at {viewport}: {metrics}"
            )
            assert not metrics["mobileTabsOverlapsHeader"], (
                f"{app_name} {route}: mobile navigation overlaps header at {viewport}: {metrics}"
            )
            if viewport == DESKTOP_VIEWPORT:
                assert not metrics["sidebarOverlapsHeader"], (
                    f"{app_name} {route}: desktop sidebar overlaps header: {metrics}"
                )

            page.close()

        context.close()


@pytest.mark.parametrize("app_name,app", [("jm", jm_app), ("my", my_app)])
def test_jm_my_dashboard_desktop_1440_has_no_horizontal_scroll(chromium_browser, app_name, app):
    client = _client_for_app(app_name, app)
    response = client.get("/")
    assert response.status_code == 200, f"{app_name} dashboard: status {response.status_code}"
    html = _inline_render_dashboard_css(response.text, client)

    context = chromium_browser.new_context(viewport=DESKTOP_VIEWPORT, java_script_enabled=False)
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda err, _e=page_errors: _e.append(str(err)))
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    metrics = _dashboard_desktop_overflow_metrics(page)
    assert metrics["viewportWidth"] == 1440, f"{app_name} dashboard: wrong viewport: {metrics}"
    assert metrics["hasDashboardGrid"], f"{app_name} dashboard: missing dashboard grid"
    assert metrics["visibleTextLength"] > 20, f"{app_name} dashboard: primary content is blank"
    assert metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} dashboard: document overflows desktop viewport: {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} dashboard: body overflows desktop viewport: {metrics}"
    )
    assert not metrics["mainContentOverflows"], (
        f"{app_name} dashboard: #mainContent has horizontal overflow: {metrics}"
    )
    assert not metrics["dashboardGridOverflows"], (
        f"{app_name} dashboard: #dashboardGrid has horizontal overflow: {metrics}"
    )
    assert not metrics["offenders"], (
        f"{app_name} dashboard: visible elements exceed 1440px viewport: {metrics}"
    )
    assert not page_errors, f"{app_name} dashboard: page errors: {page_errors}"

    page.close()
    context.close()


@pytest.mark.parametrize("app_name,app", [("jm", jm_app), ("my", my_app)])
@pytest.mark.parametrize("route", ["/", "/todos"])
def test_jm_my_global_footer_stays_stable_across_viewports(chromium_browser, app_name, app, route):
    client = _client_for_app(app_name, app)
    response = client.get(route)
    assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
    html = _inline_render_css(response.text, client)

    desktop_context = chromium_browser.new_context(viewport=DESKTOP_VIEWPORT, java_script_enabled=False)
    desktop_page = desktop_context.new_page()
    desktop_page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    desktop_page.wait_for_timeout(100)
    desktop_metrics = _global_footer_metrics(desktop_page)
    assert desktop_metrics["exists"], f"{app_name} {route}: missing mobile footer navigation"
    assert desktop_metrics["hidden"], f"{app_name} {route}: footer should be hidden on desktop: {desktop_metrics}"
    assert desktop_metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} {route}: desktop footer/layout causes horizontal scroll: {desktop_metrics}"
    )
    desktop_page.close()
    desktop_context.close()

    mobile_context = chromium_browser.new_context(viewport=MOBILE_VIEWPORT, java_script_enabled=False)
    mobile_page = mobile_context.new_page()
    mobile_page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    mobile_page.wait_for_timeout(100)
    mobile_metrics = _global_footer_metrics(mobile_page)
    assert mobile_metrics["exists"], f"{app_name} {route}: missing mobile footer navigation"
    assert mobile_metrics["visible"], f"{app_name} {route}: footer is not visible on mobile: {mobile_metrics}"
    assert mobile_metrics["pinnedToBottom"], f"{app_name} {route}: footer is not pinned to mobile bottom: {mobile_metrics}"
    assert mobile_metrics["insideViewport"], f"{app_name} {route}: footer extends outside viewport: {mobile_metrics}"
    assert mobile_metrics["itemCount"] == 5, f"{app_name} {route}: footer item count changed: {mobile_metrics}"
    assert mobile_metrics["minItemWidth"] >= 44, f"{app_name} {route}: footer item too narrow: {mobile_metrics}"
    assert mobile_metrics["minItemHeight"] >= 44, f"{app_name} {route}: footer item too short: {mobile_metrics}"
    assert mobile_metrics["documentScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, (
        f"{app_name} {route}: mobile footer/layout causes horizontal scroll: {mobile_metrics}"
    )
    assert not mobile_metrics["offenders"], f"{app_name} {route}: footer items overflow mobile viewport: {mobile_metrics}"
    mobile_page.close()
    mobile_context.close()


@pytest.mark.parametrize("app_name,app,routes", APP_CASES)
def test_jm_my_non_core_desktop_routes_keep_global_layout(chromium_browser, app_name, app, routes):
    client = _client_for_app(app_name, app)
    context = chromium_browser.new_context(viewport=DESKTOP_VIEWPORT, java_script_enabled=False)

    for route in routes:
        response = client.get(route)
        if response.status_code == 404 or 300 <= response.status_code < 400:
            continue
        assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
        html = _inline_render_css(response.text, client)

        page = context.new_page()
        page_errors = []
        page.on("pageerror", lambda err, _e=page_errors: _e.append(str(err)))
        page.set_content(html, wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(100)

        metrics = _desktop_layout_metrics(page)
        assert metrics["hasMain"], f"{app_name} {route}: missing main landmark"
        assert metrics["hasMainContent"], f"{app_name} {route}: missing #mainContent"
        assert metrics["mainVisible"], f"{app_name} {route}: main area is not visibly rendered: {metrics}"
        assert metrics["contentVisible"], f"{app_name} {route}: content area is not visibly rendered: {metrics}"
        assert metrics["sidebarVisible"], f"{app_name} {route}: desktop sidebar is not visible: {metrics}"
        assert metrics["mainAlignedAfterSidebar"], f"{app_name} {route}: main/sidebar alignment broke: {metrics}"
        assert metrics["mobileTabsHidden"], f"{app_name} {route}: mobile tab bar is visible on desktop"
        assert metrics["visibleTextLength"] > 20, f"{app_name} {route}: primary content is blank"
        assert metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
            f"{app_name} {route}: document overflows desktop viewport: {metrics}"
        )
        assert metrics["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
            f"{app_name} {route}: body overflows desktop viewport: {metrics}"
        )
        assert not page_errors, f"{app_name} {route}: page errors: {page_errors}"
        page.close()

    context.close()


@pytest.mark.parametrize("app_name,app,routes", APP_CASES)
def test_jm_my_non_core_mobile_routes_keep_navigation_and_content(chromium_browser, app_name, app, routes):
    client = _client_for_app(app_name, app)
    context = chromium_browser.new_context(viewport=MOBILE_VIEWPORT, java_script_enabled=False)

    for route in routes:
        response = client.get(route)
        if response.status_code == 404 or 300 <= response.status_code < 400:
            continue
        assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
        html = _inline_render_css(response.text, client)

        page = context.new_page()
        page_errors = []
        page.on("pageerror", lambda err, _e=page_errors: _e.append(str(err)))
        page.set_content(html, wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(100)

        metrics = _mobile_layout_metrics(page)
        assert metrics["hasMain"], f"{app_name} {route}: missing main landmark"
        assert metrics["hasMainContent"], f"{app_name} {route}: missing #mainContent"
        assert metrics["mainVisible"], f"{app_name} {route}: main area is not visibly rendered: {metrics}"
        assert metrics["contentVisible"], f"{app_name} {route}: content area is not visibly rendered: {metrics}"
        assert metrics["sidebarOffCanvas"], f"{app_name} {route}: desktop sidebar is visible on mobile: {metrics}"
        assert metrics["mobileTabsVisible"], f"{app_name} {route}: mobile tab bar is not visible: {metrics}"
        assert metrics["mobileTabsPinnedToBottom"], f"{app_name} {route}: mobile tab bar is not pinned: {metrics}"
        assert metrics["visibleTextLength"] > 20, f"{app_name} {route}: primary content is blank"
        assert metrics["documentScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, (
            f"{app_name} {route}: document overflows mobile viewport: {metrics}"
        )
        assert metrics["bodyScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, (
            f"{app_name} {route}: body overflows mobile viewport: {metrics}"
        )
        assert not metrics["offenders"], f"{app_name} {route}: elements overflow mobile viewport: {metrics}"
        assert not page_errors, f"{app_name} {route}: page errors: {page_errors}"
        page.close()

    context.close()


@pytest.mark.parametrize("app_name,app,routes", APP_CASES)
def test_jm_my_non_core_routes_keep_keyboard_accessible_interactions(chromium_browser, app_name, app, routes):
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

            metrics = _keyboard_accessibility_metrics(page)
            assert metrics["focusableCount"] > 0, f"{app_name} {route}: no keyboard focus targets"
            if metrics["mainCommandCount"] > 0:
                assert metrics["mainFocusableCount"] > 0, f"{app_name} {route}: no focusable controls in main content"
            assert not metrics["notKeyboardReachable"], (
                f"{app_name} {route}: visible command elements are not keyboard reachable: "
                f"{metrics['notKeyboardReachable']}"
            )
            assert not metrics["unlabeled"], (
                f"{app_name} {route}: visible focusable controls have no accessible label: {metrics['unlabeled']}"
            )

            sequence = _tab_sequence(page, metrics["focusableCount"] + 3)
            if metrics["mainFocusableCount"] > 0:
                assert any(item["inMain"] for item in sequence), (
                    f"{app_name} {route}: Tab order never reaches main content: {sequence}"
                )
            if viewport == MOBILE_VIEWPORT:
                assert metrics["mobileFocusable"], f"{app_name} {route}: no focusable mobile tab controls"
                assert any(item["inMobileTabs"] for item in sequence), (
                    f"{app_name} {route}: Tab order never reaches mobile navigation: {sequence}"
                )

            page.close()

        context.close()


@pytest.mark.parametrize("app_name,app,routes", APP_CASES)
def test_jm_my_non_core_routes_show_visible_focus_indicators(chromium_browser, app_name, app, routes):
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

            metrics = _keyboard_accessibility_metrics(page)
            steps = metrics["focusableCount"] + 3
            if metrics["mainFocusableCount"] > 0:
                main_indicator = _focused_indicator_after_tab_until(
                    page,
                    "Boolean(document.activeElement.closest('#mainContent'))",
                    steps,
                )
                assert main_indicator, f"{app_name} {route}: Tab order never focuses main content"
                assert main_indicator["visibleRect"], (
                    f"{app_name} {route}: focused main control is not visibly rendered: {main_indicator}"
                )
                assert main_indicator["inViewport"], (
                    f"{app_name} {route}: focused main control is outside the viewport: {main_indicator}"
                )
                assert main_indicator["hasVisibleFocusIndicator"], (
                    f"{app_name} {route}: focused main control has no visible focus indicator: {main_indicator}"
                )

            if viewport == MOBILE_VIEWPORT:
                page.evaluate("document.activeElement.blur()")
                mobile_indicator = _focused_indicator_after_tab_until(
                    page,
                    "Boolean(document.activeElement.closest('#mobileTabBar'))",
                    steps,
                )
                assert mobile_indicator, f"{app_name} {route}: Tab order never focuses mobile navigation"
                assert mobile_indicator["visibleRect"], (
                    f"{app_name} {route}: focused mobile nav control is not visibly rendered: {mobile_indicator}"
                )
                assert mobile_indicator["inViewport"], (
                    f"{app_name} {route}: focused mobile nav control is outside the viewport: {mobile_indicator}"
                )
                assert mobile_indicator["hasVisibleFocusIndicator"], (
                    f"{app_name} {route}: focused mobile nav control has no visible focus indicator: "
                    f"{mobile_indicator}"
                )

            page.close()

        context.close()
