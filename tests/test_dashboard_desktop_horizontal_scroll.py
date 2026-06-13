"""
Desktop horizontal-scroll layout checks for jm/my dashboards.

The apps are imported through conftest.py with isolated temp databases, so this
test does not touch production data. Chromium is optional; the static contract
keeps the overflow guards runnable in lighter environments.
"""

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
            profile_name = f"DashboardScroll{uuid4().hex[:8]}"
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


def _app_file(app_name: str, relative_path: str) -> str:
    return (ROOT / app_name / relative_path).read_text(encoding="utf-8")


def _inline_render_css(app_name: str, html: str) -> str:
    css_chunks = [
        _app_file(app_name, "static/tailwind.css"),
        _app_file(app_name, "static/css/app.css"),
        _app_file(app_name, "static/css/dashboard-grid.css"),
    ]
    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r'<script\b[^>]*\bsrc="[^"]+"[^>]*></script>', "", html)
    test_css = """
        *, *::before, *::after {
            animation: none !important;
            transition: none !important;
            caret-color: transparent !important;
        }
    """
    return html.replace("</head>", f"<style>{' '.join(css_chunks)} {test_css}</style></head>")


def _assert_static_horizontal_scroll_contract(app_name: str, html: str) -> None:
    app_css = _app_file(app_name, "static/css/app.css")
    dashboard_css = _app_file(app_name, "static/css/dashboard-grid.css")

    assert 'role="main"' in html
    assert 'id="mainContent"' in html
    assert 'class="dashboard-quick-actions' in html
    assert 'id="dashboardGrid"' in html
    assert 'id="dashboard-empty-state"' in html
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "#mainContent {" in app_css
    assert "max-width: 100%" in app_css
    assert "min-width: 0" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert "#dashboardGrid {\n    display: grid;" in dashboard_css
    assert "grid-template-columns: repeat(12, 1fr);" in dashboard_css
    assert ".dashboard-widget {" in dashboard_css
    assert "min-width: 0;" in dashboard_css
    assert "overflow: hidden;" in dashboard_css


def _dashboard_horizontal_scroll_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const box = (el) => {
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    className: String(el.className || '').slice(0, 140),
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    width: Math.round(rect.width),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    hasHorizontalScroll: el.scrollWidth > el.clientWidth + 2,
                };
            };
            const selectors = {
                documentElement: 'html',
                body: 'body',
                appShell: '#appShell',
                main: 'main[role="main"]',
                mainContent: '#mainContent',
                quickActions: '.dashboard-quick-actions',
                emptyState: '#dashboard-empty-state',
                dashboardGrid: '#dashboardGrid',
            };
            const allowedScrollable = (el) => {
                if (!el || !(el instanceof HTMLElement)) return false;
                if (el.closest('#sidebar')) return true;
                return Boolean(el.closest('.overflow-x-auto, .table-responsive'));
            };
            const visibleOverflowOffenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => {
                    if (!(el instanceof HTMLElement)) return false;
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return false;
                    if (allowedScrollable(el)) return false;
                    return rect.left < -2 || rect.right > viewportWidth + 2;
                })
                .slice(0, 12)
                .map(box);

            return {
                viewportWidth,
                viewportHeight: window.innerHeight,
                documentScrollWidth: document.documentElement.scrollWidth,
                bodyScrollWidth: document.body.scrollWidth,
                containers: Object.fromEntries(
                    Object.entries(selectors).map(([key, selector]) => [
                        key,
                        box(document.querySelector(selector)),
                    ])
                ),
                visibleOverflowOffenders,
            };
        }"""
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_desktop_1440_has_no_horizontal_scroll(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    _assert_static_horizontal_scroll_contract(app_name, html_response)

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

    metrics = _dashboard_horizontal_scroll_metrics(page)
    assert metrics["viewportWidth"] == DESKTOP_VIEWPORT["width"], (
        f"{app_name} /: wrong desktop viewport: {metrics}"
    )
    assert metrics["viewportHeight"] == DESKTOP_VIEWPORT["height"], (
        f"{app_name} /: wrong desktop viewport: {metrics}"
    )
    assert metrics["documentScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /: document has horizontal scroll at 1440x900: {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= DESKTOP_VIEWPORT["width"] + 2, (
        f"{app_name} /: body has horizontal scroll at 1440x900: {metrics}"
    )

    for key, container in metrics["containers"].items():
        assert container is not None, f"{app_name} /: missing {key}: {metrics}"
        assert container["right"] <= DESKTOP_VIEWPORT["width"] + 2, (
            f"{app_name} /: {key} extends past 1440px viewport: {metrics}"
        )
        assert not container["hasHorizontalScroll"], (
            f"{app_name} /: {key} has internal horizontal scroll: {metrics}"
        )

    assert not metrics["visibleOverflowOffenders"], (
        f"{app_name} /: visible dashboard elements exceed 1440px viewport: {metrics}"
    )
    assert not page_errors, f"{app_name} /: page errors: {page_errors}"

    page.close()
    context.close()
