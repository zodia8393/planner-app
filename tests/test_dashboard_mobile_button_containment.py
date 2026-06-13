"""
Independent 390x844 button-containment check for jm/my dashboards.

The apps are imported through conftest.py with isolated temp databases. The
rendered check loads the actual dashboard HTML and CSS in Chromium when
available, then verifies that visible dashboard controls stay inside their
own boxes and inside the mobile viewport.
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
            profile_name = f"DashboardButtons{uuid4().hex[:8]}"
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


def _inline_dashboard_css(app_name: str, html: str) -> str:
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


def _assert_static_button_containment_contract(app_name: str, html: str) -> None:
    app_css = _app_file(app_name, "static/css/app.css")
    dashboard_css = _app_file(app_name, "static/css/dashboard-grid.css")

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}
    assert 'role="main"' in html
    assert 'id="mainContent"' in html
    assert 'class="dashboard-quick-actions' in html
    assert 'href="/todos#new"' in html
    assert 'id="dashboard-empty-state"' in html
    assert "#mainContent :where(button, a" in app_css
    assert "max-width: 100%;" in app_css
    assert "overflow-wrap: anywhere;" in app_css
    assert ".dashboard-quick-actions {\n grid-template-columns: 1fr;" in app_css
    assert ".quick-command-card {" in app_css
    assert "min-width: 0;" in app_css
    assert ".quick-command-title,\n .quick-command-desc {" in app_css
    assert ".empty-state-primary {" in app_css
    assert "#mobileTabBar .mobile-tab-item" in app_css
    assert "#dashboardGrid {\n        grid-template-columns: 1fr;" in dashboard_css
    assert ".dashboard-widget {" in dashboard_css
    assert "overflow: hidden;" in dashboard_css


def _dashboard_button_containment_metrics(page):
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
                    && rect.height > 1
                    && rect.bottom > 0
                    && rect.top < viewportHeight;
            };
            const labelFor = (el) => (
                el.getAttribute('aria-label') ||
                el.getAttribute('title') ||
                el.innerText ||
                el.textContent ||
                ''
            ).trim().replace(/\\s+/g, ' ');
            const childOverflowFor = (el, rect) => Array.from(
                el.querySelectorAll('svg, img, span, strong, em, small')
            )
                .filter((child) => {
                    const childStyle = getComputedStyle(child);
                    const childRect = child.getBoundingClientRect();
                    if (
                        childStyle.display === 'none' ||
                        childStyle.visibility === 'hidden' ||
                        childRect.width <= 0 ||
                        childRect.height <= 0
                    ) return false;
                    return childRect.left < rect.left - 2
                        || childRect.right > rect.right + 2
                        || childRect.top < rect.top - 2
                        || childRect.bottom > rect.bottom + 2;
                })
                .slice(0, 4)
                .map((child) => {
                    const childRect = child.getBoundingClientRect();
                    return {
                        tag: child.tagName.toLowerCase(),
                        text: (child.innerText || child.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 60),
                        left: Math.round(childRect.left),
                        right: Math.round(childRect.right),
                        top: Math.round(childRect.top),
                        bottom: Math.round(childRect.bottom),
                    };
                });
            const describe = (el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                const clipsOwnContent = (
                    (style.overflowX !== 'visible' && el.scrollWidth > el.clientWidth + 2) ||
                    (style.overflowY !== 'visible' && el.scrollHeight > el.clientHeight + 2)
                );
                const outsideViewport = rect.left < -2
                    || rect.right > viewportWidth + 2
                    || rect.top < -2
                    || rect.bottom > viewportHeight + 2;
                const parent = el.parentElement?.getBoundingClientRect();
                const outsideParent = parent ? (
                    rect.left < parent.left - 2 ||
                    rect.right > parent.right + 2 ||
                    rect.top < parent.top - 2 ||
                    rect.bottom > parent.bottom + 2
                ) : false;

                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    href: el.getAttribute('href') || '',
                    role: el.getAttribute('role') || '',
                    label: labelFor(el).slice(0, 90),
                    className: String(el.className || '').slice(0, 140),
                    whiteSpace: style.whiteSpace,
                    overflowX: style.overflowX,
                    overflowY: style.overflowY,
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    top: Math.round(rect.top),
                    bottom: Math.round(rect.bottom),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    outsideViewport,
                    outsideParent,
                    clipsOwnContent,
                    childOverflow: childOverflowFor(el, rect),
                };
            };

            const checks = Array.from(document.querySelectorAll(controlSelector)).filter(isVisible);
            const failures = checks
                .map(describe)
                .filter((item) => (
                    item.outsideViewport ||
                    item.outsideParent ||
                    item.clipsOwnContent ||
                    item.childOverflow.length > 0
                ));

            return {
                viewportWidth,
                viewportHeight,
                checkedCount: checks.length,
                labels: checks.map(labelFor).filter(Boolean),
                failures,
            };
        }"""
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_mobile_390x844_buttons_stay_inside_containers_and_viewport(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    _assert_static_button_containment_contract(app_name, html_response)

    if optional_chromium_browser is None:
        return

    context = optional_chromium_browser.new_context(
        viewport=MOBILE_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page.set_content(_inline_dashboard_css(app_name, html_response), wait_until="domcontentloaded")
    page.wait_for_timeout(100)
    metrics = _dashboard_button_containment_metrics(page)

    assert metrics["viewportWidth"] == MOBILE_VIEWPORT["width"], metrics
    assert metrics["viewportHeight"] == MOBILE_VIEWPORT["height"], metrics
    assert metrics["checkedCount"] >= 4, f"{app_name} /: no visible dashboard controls: {metrics}"
    assert any("할일" in label for label in metrics["labels"]), (
        f"{app_name} /: core todo entry button was not rendered: {metrics}"
    )
    assert not metrics["failures"], (
        f"{app_name} / at 390x844: dashboard buttons are clipped or outside containers: {metrics}"
    )

    page.close()
    context.close()
