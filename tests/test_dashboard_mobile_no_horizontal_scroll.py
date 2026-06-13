"""
Independent rendered 390x844 horizontal-scroll check for jm/my dashboards.

This test is intentionally narrow: it loads each dashboard at the MVP mobile
viewport and fails when the document, body, or primary dashboard containers
create horizontal overflow.
"""

import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from conftest import jm_app, jm_mod, my_app, my_mod, run_async


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


def _inline_dashboard_css(app_name: str, html: str) -> str:
    css_chunks = [
        (ROOT / app_name / "static" / "tailwind.css").read_text(encoding="utf-8"),
        (ROOT / app_name / "static" / "css" / "app.css").read_text(encoding="utf-8"),
        (ROOT / app_name / "static" / "css" / "dashboard-grid.css").read_text(
            encoding="utf-8"
        ),
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


def _horizontal_scroll_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const sizeFor = (name, el) => {
                if (!el) return null;
                return {
                    name,
                    clientWidth: el.clientWidth,
                    scrollWidth: el.scrollWidth,
                    overflowBy: Math.max(0, el.scrollWidth - el.clientWidth),
                };
            };
            const containers = [
                sizeFor('documentElement', document.documentElement),
                sizeFor('body', document.body),
                sizeFor('main', document.querySelector('main[role="main"]')),
                sizeFor('mainContent', document.querySelector('#mainContent')),
                sizeFor('quickActions', document.querySelector('.dashboard-quick-actions')),
                sizeFor('dashboardGrid', document.querySelector('#dashboardGrid')),
            ].filter(Boolean);
            const visibleOffenders = Array.from(document.body.querySelectorAll('*'))
                .filter((el) => el instanceof HTMLElement)
                .filter((el) => !el.closest('#sidebar, .overflow-x-auto, .table-responsive'))
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 120),
                        left: Math.round(rect.left),
                        right: Math.round(rect.right),
                        width: Math.round(rect.width),
                    };
                })
                .filter((item) => item.width > 0 && (item.left < -2 || item.right > viewportWidth + 2))
                .slice(0, 10);
            return {
                viewportWidth,
                viewportHeight: window.innerHeight,
                containers,
                visibleOffenders,
            };
        }"""
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_mobile_390x844_has_no_horizontal_scroll(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    app_css = (ROOT / app_name / "static" / "css" / "app.css").read_text(encoding="utf-8")
    dashboard_css = (ROOT / app_name / "static" / "css" / "dashboard-grid.css").read_text(
        encoding="utf-8"
    )

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}
    assert 'role="main"' in html_response
    assert 'id="mainContent"' in html_response
    assert 'class="dashboard-quick-actions' in html_response
    assert 'id="dashboardGrid"' in html_response

    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert ".dashboard-quick-actions {\n grid-template-columns: 1fr;" in app_css
    assert "input, select, textarea { max-width: 100%; box-sizing: border-box; }" in app_css
    assert "#dashboardGrid {\n        grid-template-columns: 1fr;" in dashboard_css
    assert ".dashboard-widget {" in dashboard_css
    assert "overflow: hidden;" in dashboard_css
    assert "min-width: 0;" in dashboard_css

    if optional_chromium_browser is None:
        return

    context = optional_chromium_browser.new_context(
        viewport=MOBILE_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page.set_content(_inline_dashboard_css(app_name, html_response), wait_until="domcontentloaded")
    page.wait_for_timeout(100)

    metrics = _horizontal_scroll_metrics(page)

    assert metrics["viewportWidth"] == MOBILE_VIEWPORT["width"], metrics
    assert metrics["viewportHeight"] == MOBILE_VIEWPORT["height"], metrics
    assert not metrics["visibleOffenders"], (
        f"{app_name} /: visible dashboard elements extend beyond 390px viewport: {metrics}"
    )
    for container in metrics["containers"]:
        assert container["overflowBy"] <= 2, (
            f"{app_name} /: {container['name']} has horizontal scroll at 390x844: {metrics}"
        )

    page.close()
    context.close()
