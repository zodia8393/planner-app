"""
Rendered color-contrast checks for visible text on jm/my dashboards.

The apps come from conftest.py with isolated temp databases, so this test does
not touch production data. Chromium is optional in this project; when available
the test verifies computed foreground/background colors for every visible
dashboard text node against WCAG AA contrast thresholds.
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


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        if normalized <= 0.03928:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    red, green, blue = rgb
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def _contrast_ratio(foreground: str, background: str) -> float:
    fg_luminance = _relative_luminance(_hex_to_rgb(foreground))
    bg_luminance = _relative_luminance(_hex_to_rgb(background))
    lighter = max(fg_luminance, bg_luminance)
    darker = min(fg_luminance, bg_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _css_tokens(css: str) -> dict[str, str]:
    root_match = re.search(r":root\s*\{(?P<body>.*?)\n\s*\}", css, re.S)
    assert root_match, "missing :root design tokens"
    tokens: dict[str, str] = {}
    for name, value in re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", root_match.group("body")):
        tokens[name] = value.lower()
    return tokens


def _assert_static_dashboard_contrast_contract(app_name: str, html: str) -> None:
    app_css = _app_css(app_name, "static/css/app.css")
    tokens = _css_tokens(app_css)
    required_pairs = [
        ("--color-text", "--color-bg", 4.5),
        ("--color-text", "--color-surface", 4.5),
        ("--color-text-muted", "--color-bg", 4.5),
        ("--color-text-muted", "--color-surface", 4.5),
        ("--color-text-faint", "--color-bg", 4.5),
        ("--color-text-faint", "--color-surface", 4.5),
        ("--color-text-faint", "--color-border-subtle", 4.5),
        ("--color-accent-text", "--color-accent-soft", 4.5),
    ]
    for foreground, background, minimum in required_pairs:
        ratio = _contrast_ratio(tokens[foreground], tokens[background])
        assert ratio >= minimum, (
            f"{app_name}: {foreground} on {background} contrast {ratio:.2f} < {minimum}"
        )

    accent_hover_ratio = _contrast_ratio("#ffffff", tokens["--color-accent-hover"])
    assert accent_hover_ratio >= 4.5, (
        f"{app_name}: white text on --color-accent-hover contrast "
        f"{accent_hover_ratio:.2f} < 4.5"
    )

    assert ".empty-state-primary {\n color: #fff;\n background: var(--color-accent-hover);" in app_css
    assert ".quick-command-icon {\n width: 2rem;" in app_css
    assert "color: #fff;\n background: var(--color-accent-hover);" in app_css
    assert "#dashboardGrid .btn-accent {\n background: var(--color-accent-hover);\n }" in app_css
    assert "background: var(--color-accent); color: white;" not in html
    assert "background: var(--color-accent-hover); color: white;" in html


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
            profile_name = f"DashboardContrast{uuid4().hex[:8]}"
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


def _insert_contrast_todo(mod, profile_id: int, app_name: str) -> None:
    with mod.get_db() as conn:
        conn.execute("DELETE FROM todos WHERE profile_id=?", (profile_id,))
        conn.execute(
            """
            INSERT INTO todos (
                profile_id, title, description, priority, due_date, tags,
                assignee, energy_level, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                f"{app_name.upper()} contrast audit todo",
                "Screen-level color contrast check item.",
                1,
                "2026-06-12",
                '["contrast", "a11y"]',
                app_name.upper(),
                3,
                1,
            ),
        )


async def _fetch_core_todo_html(app_name: str, app, mod) -> str:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"TodoContrast{uuid4().hex[:8]}"
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

        _insert_contrast_todo(mod, profile_id, app_name)
        response = await client.get("/todos")
        assert response.status_code == 200, f"{app_name} /todos: status {response.status_code}"
        return response.text


async def _fetch_non_core_htmls(app_name: str, app) -> dict[str, str]:
    routes = COMMON_NON_CORE_ROUTES + (["/files"] if app_name == "my" else [])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        if app_name == "my":
            response = await client.post(
                "/setup",
                data={"name": f"NonCoreContrast{uuid4().hex[:8]}"},
                headers=ORIGIN,
                follow_redirects=False,
            )
            assert response.status_code == 303

        html_by_route = {}
        for route in routes:
            response = await client.get(route)
            if response.status_code == 404 or 300 <= response.status_code < 400:
                continue
            assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
            html_by_route[route] = response.text
        return html_by_route


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
    return html.replace("</head>", f"<style>{' '.join(css_chunks)}</style></head>")


def _assert_static_core_todo_contrast_contract(app_name: str, html: str) -> None:
    app_css = _app_css(app_name, "static/css/app.css")
    tokens = _css_tokens(app_css)
    required_pairs = [
        ("--color-text", "--color-bg", 4.5),
        ("--color-text", "--color-surface", 4.5),
        ("--color-text-muted", "--color-bg", 4.5),
        ("--color-text-muted", "--color-surface", 4.5),
        ("--color-text-faint", "--color-bg", 4.5),
        ("--color-text-faint", "--color-surface", 4.5),
        ("--color-accent-text", "--color-accent-soft", 4.5),
        ("--color-danger", "--color-danger-soft", 4.5),
        ("--color-info", "--color-info-soft", 4.5),
        ("--color-success", "--color-success-soft", 4.5),
        ("--color-warning", "--color-warning-soft", 4.5),
    ]
    for foreground, background, minimum in required_pairs:
        ratio = _contrast_ratio(tokens[foreground], tokens[background])
        assert ratio >= minimum, (
            f"{app_name}: {foreground} on {background} contrast {ratio:.2f} < {minimum}"
        )

    for background in ("--color-success", "--color-warning", "--color-danger", "--color-info"):
        ratio = _contrast_ratio("#ffffff", tokens[background])
        assert ratio >= 4.5, (
            f"{app_name}: white text on {background} contrast {ratio:.2f} < 4.5"
        )

    assert "업무 관리" in html
    assert 'aria-label="할일 목록"' in html
    assert 'id="todoList"' in html
    assert 'id="addForm"' in html
    assert 'aria-label="새 업무 제목"' in html
    assert "contrast audit todo" in html


def _dashboard_text_contrast_metrics(page):
    return page.evaluate(
        """() => {
            const parseColor = (value) => {
                if (!value) return null;
                const match = value.match(/rgba?\\(([^)]+)\\)/);
                if (!match) return null;
                const parts = match[1].split(',').map((part) => part.trim());
                return {
                    r: Number(parts[0]),
                    g: Number(parts[1]),
                    b: Number(parts[2]),
                    a: parts.length > 3 ? Number(parts[3]) : 1,
                };
            };
            const blend = (top, bottom) => {
                if (!top) return bottom;
                if (top.a >= 1) return {...top, a: 1};
                const a = top.a + bottom.a * (1 - top.a);
                return {
                    r: (top.r * top.a + bottom.r * bottom.a * (1 - top.a)) / a,
                    g: (top.g * top.a + bottom.g * bottom.a * (1 - top.a)) / a,
                    b: (top.b * top.a + bottom.b * bottom.a * (1 - top.a)) / a,
                    a,
                };
            };
            const luminance = (color) => {
                const channel = (value) => {
                    const normalized = value / 255;
                    return normalized <= 0.03928
                        ? normalized / 12.92
                        : Math.pow((normalized + 0.055) / 1.055, 2.4);
                };
                return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
            };
            const contrastRatio = (a, b) => {
                const lighter = Math.max(luminance(a), luminance(b));
                const darker = Math.min(luminance(a), luminance(b));
                return (lighter + 0.05) / (darker + 0.05);
            };
            const gradientStops = (value) => {
                const matches = value.match(/rgba?\\([^)]+\\)/g);
                return matches ? matches.map(parseColor).filter(Boolean) : [];
            };
            const effectiveBackgrounds = (el) => {
                const canvas = {r: 255, g: 255, b: 255, a: 1};
                for (let node = el; node && node.nodeType === Node.ELEMENT_NODE; node = node.parentElement) {
                    const style = getComputedStyle(node);
                    const color = parseColor(style.backgroundColor);
                    const base = color && color.a > 0.02 ? blend(color, canvas) : null;
                    const stops = gradientStops(style.backgroundImage);
                    if (stops.length) {
                        const underlay = base || canvas;
                        return stops.map((stop) => blend(stop, underlay));
                    }
                    if (base) return [base];
                }
                return [canvas];
            };
            const isVisibleRect = (rect) => (
                rect.width > 1 &&
                rect.height > 1 &&
                rect.right > 0 &&
                rect.bottom > 0 &&
                rect.left < window.innerWidth &&
                rect.top < window.innerHeight
            );
            const textItems = [];
            const elements = [document.body, ...document.body.querySelectorAll('*')];
            elements.forEach((parent) => {
                if (parent.closest('[aria-hidden="true"], script, style, .sr-only')) return;
                const style = getComputedStyle(parent);
                if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) {
                    return;
                }
                const text = (parent.innerText || parent.textContent || '').replace(/\\s+/g, ' ').trim();
                if (!text) return;
                const rect = parent.getBoundingClientRect();
                if (!isVisibleRect(rect)) return;
                const hasVisibleTextChild = Array.from(parent.children).some((child) => {
                    if (child.closest('[aria-hidden="true"], script, style, .sr-only')) return false;
                    const childStyle = getComputedStyle(child);
                    if (
                        childStyle.display === 'none' ||
                        childStyle.visibility === 'hidden' ||
                        Number(childStyle.opacity) === 0
                    ) {
                        return false;
                    }
                    const childText = (child.innerText || child.textContent || '').replace(/\\s+/g, ' ').trim();
                    return childText && isVisibleRect(child.getBoundingClientRect());
                });
                if (hasVisibleTextChild) return;
                textItems.push({parent, text, rect});
            });

            const checked = [];
            const offenders = [];
            textItems.forEach(({parent, text, rect}) => {
                const style = getComputedStyle(parent);
                const color = parseColor(style.color);
                if (!color || color.a === 0) return;
                const backgrounds = effectiveBackgrounds(parent);
                const ratios = backgrounds.map((background) => contrastRatio(color, background));
                const ratio = Math.min(...ratios);
                const fontSize = Number.parseFloat(style.fontSize) || 16;
                const fontWeight = Number.parseInt(style.fontWeight, 10) || 400;
                const isLargeText = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700);
                const requiredRatio = isLargeText ? 3 : 4.5;
                const item = {
                    text: text.slice(0, 80),
                    tag: parent.tagName.toLowerCase(),
                    id: parent.id || '',
                    className: String(parent.className || '').slice(0, 140),
                    color: style.color,
                    background: backgrounds.map((background) => (
                        `rgb(${Math.round(background.r)}, ${Math.round(background.g)}, ${Math.round(background.b)})`
                    )),
                    fontSize,
                    fontWeight,
                    ratio: Number(ratio.toFixed(2)),
                    requiredRatio,
                    box: [
                        Math.round(rect.left), Math.round(rect.top),
                        Math.round(rect.right), Math.round(rect.bottom),
                    ],
                };
                checked.push(item);
                if (ratio + 0.01 < requiredRatio) offenders.push(item);
            });
            return {
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
                checkedCount: checked.length,
                offenders: offenders.slice(0, 20),
            };
        }"""
    )


def _assert_rendered_text_contrast(app_name: str, path: str, html_response: str, browser) -> None:
    html = _inline_render_css(app_name, html_response)
    for viewport in (DESKTOP_VIEWPORT, MOBILE_VIEWPORT):
        context = browser.new_context(viewport=viewport, java_script_enabled=False)
        page = context.new_page()
        page.set_content(html, wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(100)

        metrics = _dashboard_text_contrast_metrics(page)
        assert metrics["viewportWidth"] == viewport["width"], (
            f"{app_name} {path}: wrong contrast viewport: {metrics}"
        )
        assert metrics["checkedCount"] >= 5, (
            f"{app_name} {path}: visible text contrast candidates were not rendered: {metrics}"
        )
        assert not metrics["offenders"], (
            f"{app_name} {path}: visible text fails contrast thresholds: {metrics}"
        )

        page.close()
        context.close()


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_visible_text_has_accessible_color_contrast(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    assert "대시보드" in html_response
    assert 'id="mainContent"' in html_response
    assert 'class="common-app-header' in html_response
    _assert_static_dashboard_contrast_contract(app_name, html_response)

    if optional_chromium_browser is None:
        return

    html = _inline_render_css(app_name, html_response)
    context = optional_chromium_browser.new_context(
        viewport=DESKTOP_VIEWPORT, java_script_enabled=False
    )
    page = context.new_page()
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    metrics = _dashboard_text_contrast_metrics(page)
    assert metrics["viewportWidth"] == DESKTOP_VIEWPORT["width"], (
        f"{app_name} /: wrong contrast viewport: {metrics}"
    )
    assert metrics["checkedCount"] >= 5, (
        f"{app_name} /: dashboard text contrast candidates were not rendered: {metrics}"
    )
    assert not metrics["offenders"], (
        f"{app_name} /: visible dashboard text fails contrast thresholds: {metrics}"
    )

    page.close()
    context.close()


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_screen_visible_text_has_accessible_color_contrast(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_core_todo_html(app_name, app, mod))
    _assert_static_core_todo_contrast_contract(app_name, html_response)

    if optional_chromium_browser is None:
        return

    _assert_rendered_text_contrast(app_name, "/todos", html_response, optional_chromium_browser)


@pytest.mark.parametrize("app_name,app", [("jm", jm_app), ("my", my_app)])
def test_jm_my_non_core_major_text_and_status_have_accessible_color_contrast(
    optional_chromium_browser, app_name, app
):
    html_by_route = run_async(_fetch_non_core_htmls(app_name, app))
    assert html_by_route, f"{app_name}: no non-core routes rendered"

    app_css = _app_css(app_name, "static/css/app.css")
    tokens = _css_tokens(app_css)
    required_pairs = [
        ("--color-text-faint", "--color-bg", 4.5),
        ("--color-text-faint", "--color-surface", 4.5),
        ("--color-danger", "--color-bg", 4.5),
        ("--color-danger", "--color-surface", 4.5),
        ("--color-danger", "--color-danger-soft", 4.5),
        ("--color-info", "--color-bg", 4.5),
        ("--color-info", "--color-surface", 4.5),
        ("--color-info", "--color-info-soft", 4.5),
        ("--color-success", "--color-bg", 4.5),
        ("--color-success", "--color-surface", 4.5),
        ("--color-success", "--color-success-soft", 4.5),
        ("--color-warning", "--color-bg", 4.5),
        ("--color-warning", "--color-surface", 4.5),
        ("--color-warning", "--color-warning-soft", 4.5),
    ]
    for foreground, background, minimum in required_pairs:
        ratio = _contrast_ratio(tokens[foreground], tokens[background])
        assert ratio >= minimum, (
            f"{app_name}: non-core {foreground} on {background} "
            f"contrast {ratio:.2f} < {minimum}"
        )

    assert "non-core status/text contrast guard" in app_css
    for selector in (
        ".text-slate-400",
        ".text-red-400",
        ".text-blue-400",
        ".text-indigo-500",
        ".text-green-600",
        ".text-amber-400",
    ):
        assert selector in app_css

    if optional_chromium_browser is None:
        return

    for route, html_response in html_by_route.items():
        _assert_rendered_text_contrast(
            app_name, route, html_response, optional_chromium_browser
        )
