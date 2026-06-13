"""
Independent 390x844 text-overlap checks for the jm/my MVP dashboards.

This file is intentionally scoped to the dashboard major-text requirement. The
app fixtures in conftest.py use isolated temporary databases, so the check does
not write to production planner data.
"""

import pytest

from conftest import jm_app, jm_mod, my_app, my_mod, run_async
from test_dashboard_mobile_responsive import (
    MOBILE_VIEWPORT,
    _dashboard_mobile_text_metrics,
    _fetch_dashboard_html,
    _inline_render_css,
    optional_chromium_browser,
)


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_mobile_390_major_text_elements_do_not_overlap(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}
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
    assert not metrics["overlaps"], (
        f"{app_name} /: major dashboard text elements overlap at 390x844: {metrics}"
    )

    page_errors = [err for err in page_errors if "localStorage" not in err]
    assert not page_errors, f"{app_name} /: page errors: {page_errors}"

    page.close()
    context.close()
