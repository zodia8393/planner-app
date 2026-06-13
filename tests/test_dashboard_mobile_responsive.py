"""
Independent 390x844 mobile overflow and text-overlap checks for jm/my dashboards.

The static contract keeps the responsive CSS hooks explicit. When Chromium is
available, the rendered check loads the actual dashboard HTML in a 390x844
viewport and verifies that major visible text stays inside its containers
without overlapping other major text.
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
    if sync_playwright is None or not _can_launch_chromium():
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
            profile_name = f"DashboardMobile{uuid4().hex[:8]}"
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


def _dashboard_mobile_text_metrics(page):
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
            const textOverflowOffenders = items
                .filter((item) => item.left < -2 || item.right > viewportWidth + 2)
                .slice(0, 8)
                .map((item) => ({
                    tag: item.tag,
                    id: item.id,
                    className: item.className,
                    text: item.text,
                    left: Math.round(item.left),
                    right: Math.round(item.right),
                }));

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
                textOverflowOffenders,
            };
        }"""
    )


def _dashboard_mobile_action_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const selectors = [
                ['header-sidebar', '.common-app-header [data-action="toggle-sidebar"]'],
                ['header-notifications', '.common-app-header [data-action="toggle-notif-panel"]'],
                ['quick-actions', '.dashboard-quick-actions .quick-command-card'],
                ['empty-state-primary', '#dashboard-empty-state .empty-state-primary'],
                ['mobile-tabs', '#mobileTabBar .mobile-tab-item'],
                ['focus-open', '#focusBtn']
            ];
            const items = selectors.flatMap(([group, selector]) => {
                return Array.from(document.querySelectorAll(selector))
                    .filter((el) => el instanceof HTMLElement)
                    .filter((el) => {
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    })
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        const label = el.getAttribute('aria-label') ||
                            el.textContent.replace(/\\s+/g, ' ').trim() ||
                            el.getAttribute('title') ||
                            selector;
                        return {
                            group,
                            label,
                            tag: el.tagName.toLowerCase(),
                            id: el.id || '',
                            className: String(el.className || '').slice(0, 120),
                            left: Math.round(rect.left),
                            right: Math.round(rect.right),
                            top: Math.round(rect.top),
                            bottom: Math.round(rect.bottom),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        };
                    });
            });
            const offscreen = items.filter((item) => (
                item.left < -2 ||
                item.right > viewportWidth + 2 ||
                item.top < -2 ||
                item.bottom > viewportHeight + 2
            ));
            const tooSmall = items.filter((item) => item.width < 44 || item.height < 44);
            const byGroup = items.reduce((acc, item) => {
                acc[item.group] = (acc[item.group] || 0) + 1;
                return acc;
            }, {});
            return {
                viewportWidth,
                viewportHeight,
                count: items.length,
                byGroup,
                items,
                offscreen,
                tooSmall,
            };
        }"""
    )


@pytest.mark.parametrize("app_name", ["jm", "my"])
def test_jm_my_dashboard_has_no_mobile_horizontal_scroll_contract(app_name: str):
    template = (ROOT / app_name / "templates" / "dashboard.html").read_text(encoding="utf-8")
    app_css = (ROOT / app_name / "static" / "css" / "app.css").read_text(encoding="utf-8")
    dashboard_css = (ROOT / app_name / "static" / "css" / "dashboard-grid.css").read_text(
        encoding="utf-8"
    )

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}

    assert 'class="dashboard-quick-actions' in template
    assert 'aria-label="빠른 작업"' in template
    assert 'id="dashboardGrid"' in template
    assert '{% include"widgets/widget_row.html" %}' in template
    assert '{% include"widgets/quick_add.html" %}' in template
    assert '{% include"widgets/plan_view.html" %}' in template

    assert "*, *::before, *::after { box-sizing: border-box; }" in app_css
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "#mainContent {" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert "#mainContent :where(.work-card, details, section, article, form, table)" in app_css
    assert "#mainContent :where(button, a, .btn-accent" in app_css

    assert "@media (max-width: 640px)" in app_css
    assert ".dashboard-quick-actions {\n grid-template-columns: 1fr;" in app_css
    assert ".quick-command-card,\n .empty-state-primary,\n .empty-state-secondary {\n width: 100%;" in app_css
    assert "input, select, textarea { max-width: 100%; box-sizing: border-box; }" in app_css

    assert "#dashboardGrid {\n    display: grid;" in dashboard_css
    assert "#dashboardGrid {\n        grid-template-columns: 1fr;" in dashboard_css
    assert "@media (max-width: 767px)" in dashboard_css
    assert ".dashboard-widget {" in dashboard_css
    assert "overflow: hidden;" in dashboard_css
    assert "min-width: 0;" in dashboard_css
    assert ".dashboard-widget[data-widget=\"widget-row\"]    { grid-column: span 1;" in dashboard_css
    assert ".dashboard-widget[data-widget=\"quick-add\"]     { grid-column: span 1;" in dashboard_css
    assert ".dashboard-widget[data-widget=\"plan-view\"]     { grid-column: span 1;" in dashboard_css


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_mobile_390_major_actions_are_contained_and_touch_sized(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    app_css = _app_css(app_name, "static/css/app.css")

    assert 'aria-label="빠른 작업"' in html_response
    assert 'class="quick-command-card"' in html_response
    assert 'class="empty-state-primary inline-flex' in html_response
    assert 'id="mobileTabBar"' in html_response
    assert 'id="focusBtn"' in html_response
    assert "button, a.inline-flex, [role=\"button\"], .nav-item" in app_css
    assert ".quick-command-card,\n .empty-state-primary,\n .empty-state-secondary {\n width: 100%;" in app_css
    assert ".mobile-tab-item {\n position: relative;" in app_css
    assert "min-height: 2.75rem;" in app_css

    if optional_chromium_browser is None:
        return

    html = _inline_render_css(app_name, html_response)
    context = optional_chromium_browser.new_context(
        viewport=MOBILE_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    metrics = _dashboard_mobile_action_metrics(page)
    expected_groups = {
        "header-sidebar": 1,
        "header-notifications": 1,
        "quick-actions": 3,
        "empty-state-primary": 1,
        "mobile-tabs": 5,
        "focus-open": 1,
    }

    assert metrics["viewportWidth"] == MOBILE_VIEWPORT["width"], (
        f"{app_name} /: wrong mobile viewport for dashboard actions: {metrics}"
    )
    assert metrics["viewportHeight"] == MOBILE_VIEWPORT["height"], (
        f"{app_name} /: wrong mobile viewport for dashboard actions: {metrics}"
    )
    for group, expected_count in expected_groups.items():
        assert metrics["byGroup"].get(group) == expected_count, (
            f"{app_name} /: missing visible mobile dashboard action group {group}: {metrics}"
        )
    assert metrics["count"] >= sum(expected_groups.values()), (
        f"{app_name} /: dashboard mobile actions were not rendered: {metrics}"
    )
    assert not metrics["offscreen"], (
        f"{app_name} /: mobile dashboard actions extend outside 390x844 viewport: {metrics}"
    )
    assert not metrics["tooSmall"], (
        f"{app_name} /: mobile dashboard actions are below 44px touch target: {metrics}"
    )

    page.close()
    context.close()


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_mobile_390_major_text_does_not_overlap_or_overflow(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    assert 'role="main"' in html_response
    assert 'id="mainContent"' in html_response
    assert 'aria-label="빠른 작업"' in html_response
    assert 'id="dashboard-empty-state"' in html_response
    assert 'id="dashboardGrid"' in html_response

    if optional_chromium_browser is None:
        return

    html = _inline_render_css(app_name, html_response)
    context = optional_chromium_browser.new_context(
        viewport=MOBILE_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda err, _e=page_errors: _e.append(str(err)))
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    metrics = _dashboard_mobile_text_metrics(page)
    assert metrics["viewportWidth"] == MOBILE_VIEWPORT["width"], (
        f"{app_name} /: wrong mobile viewport: {metrics}"
    )
    assert metrics["viewportHeight"] == MOBILE_VIEWPORT["height"], (
        f"{app_name} /: wrong mobile viewport: {metrics}"
    )
    assert metrics["textElementCount"] >= 12, (
        f"{app_name} /: dashboard mobile text candidates were not rendered: {metrics}"
    )
    assert metrics["documentScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, (
        f"{app_name} /: document overflows 390px mobile viewport: {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, (
        f"{app_name} /: body overflows 390px mobile viewport: {metrics}"
    )

    for key, rect in metrics["containers"].items():
        assert rect, f"{app_name} /: missing mobile {key}: {metrics}"
        assert rect["right"] <= MOBILE_VIEWPORT["width"] + 2, (
            f"{app_name} /: mobile {key} exceeds 390px viewport: {metrics}"
        )
        assert not rect["hasHorizontalScroll"], (
            f"{app_name} /: mobile {key} has internal horizontal scroll: {metrics}"
        )

    assert not metrics["overflowOffenders"], (
        f"{app_name} /: visible elements exceed 390px mobile viewport: {metrics}"
    )
    assert not metrics["textOverflowOffenders"], (
        f"{app_name} /: major dashboard text exceeds 390px mobile viewport: {metrics}"
    )
    assert not metrics["overlaps"], (
        f"{app_name} /: major dashboard text elements overlap at 390x844: {metrics}"
    )
    page_errors = [err for err in page_errors if "localStorage" not in err]
    assert not page_errors, f"{app_name} /: page errors: {page_errors}"

    page.close()
    context.close()
