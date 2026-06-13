"""
Independent 390x844 UI checks for jm/my todo creation touch controls.

The app fixtures render against isolated temporary databases. The test does not
create todos, so it leaves no persistent user data behind.
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
MIN_TOUCH_TARGET_PX = 44
ORIGIN = {"origin": "http://testserver", "host": "testserver"}


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


async def _fetch_todo_creation_html(app_name: str, app, mod) -> str:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        if app_name == "my":
            profile_name = f"CreationTouch{uuid4().hex[:8]}"
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

        response = await client.get("/todos")
        assert response.status_code == 200, f"{app_name} /todos: {response.status_code}"
        return response.text


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


def _assert_static_touch_contract(app_name: str, html: str) -> None:
    template = _asset_text(app_name, "templates/todos.html")
    app_css = _asset_text(app_name, "static/css/app.css")

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}
    assert 'id="todoPage"' in html
    assert 'id="addForm"' in html
    assert 'id="addFormOptions"' in html
    assert 'aria-label="새 업무 제목"' in html
    assert 'aria-label="마감일"' in html
    assert 'aria-label="우선순위"' in html
    assert 'aria-label="카테고리"' in html
    assert 'aria-label="반복 설정"' in html
    assert 'aria-label="에너지 레벨"' in html
    assert 'aria-label="태그"' in html
    assert 'aria-label="설명 필드 표시"' in html
    assert 'aria-label="알림 시간 선택"' in html
    assert 'aria-label="알림 추가"' in html
    assert 'aria-label="설명"' in html

    assert 'class="flex gap-2"' in template
    assert 'class="flex flex-wrap items-center gap-1.5"' in template
    assert 'class="flex gap-1.5"' in template
    assert 'class="w-full mt-2 px-3 py-2 text-sm border rounded-lg focus-accent hidden"' in template

    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "#mainContent :where(button, a, .btn-accent" in app_css
    assert "#todoPage #addForm :where(input:not([type=\"hidden\"]):not([type=\"checkbox\"]):not([type=\"radio\"]), select, textarea, button, summary)" in app_css
    assert "min-height: 2.75rem;" in app_css
    assert "input, select, textarea { max-width: 100%; box-sizing: border-box; }" in app_css
    assert ".flex { min-width: 0; }" in app_css
    assert ".flex > * { min-width: 0; }" in app_css


def _creation_touch_metrics(page):
    return page.evaluate(
        """() => {
            const viewportWidth = window.innerWidth;
            const details = document.querySelector('#addFormOptions');
            if (details) details.open = true;
            const addForm = document.querySelector('#addForm');
            const formRect = addForm.getBoundingClientRect();
            const controls = Array.from(document.querySelectorAll([
                '#addForm input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])',
                '#addForm select',
                '#addForm textarea',
                '#addForm button',
                '#addForm summary'
            ].join(','))).filter((el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && rect.width > 1
                    && rect.height > 1;
            }).map((el) => {
                const rect = el.getBoundingClientRect();
                const label = el.getAttribute('aria-label')
                    || el.getAttribute('placeholder')
                    || el.textContent.trim().replace(/\\s+/g, ' ');
                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    label,
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    minHeight: window.getComputedStyle(el).minHeight,
                };
            });
            return {
                viewportWidth,
                documentScrollWidth: document.documentElement.scrollWidth,
                bodyScrollWidth: document.body.scrollWidth,
                form: {
                    left: Math.round(formRect.left),
                    right: Math.round(formRect.right),
                    width: Math.round(formRect.width),
                    scrollWidth: addForm.scrollWidth,
                    clientWidth: addForm.clientWidth,
                },
                controlCount: controls.length,
                clippedControls: controls.filter((control) =>
                    control.left < formRect.left - 2
                    || control.right > formRect.right + 2
                    || control.left < -2
                    || control.right > viewportWidth + 2
                ),
                undersizedControls: controls.filter((control) =>
                    control.height < 44
                    || (control.tag === 'button' && control.width < 44)
                ),
            };
        }"""
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_todo_creation_mobile_390_touch_controls_are_visible_contained_and_sized(
    optional_chromium_browser, app_name, app, mod
):
    html_response = run_async(_fetch_todo_creation_html(app_name, app, mod))
    _assert_static_touch_contract(app_name, html_response)

    if optional_chromium_browser is None:
        return

    html = _inline_render_css(app_name, html_response)
    context = optional_chromium_browser.new_context(
        viewport=MOBILE_VIEWPORT,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda err, _errors=page_errors: _errors.append(str(err)))
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    metrics = _creation_touch_metrics(page)
    assert metrics["viewportWidth"] == MOBILE_VIEWPORT["width"], metrics
    assert metrics["controlCount"] >= 12, metrics
    assert metrics["documentScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, metrics
    assert metrics["bodyScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, metrics
    assert metrics["form"]["right"] <= MOBILE_VIEWPORT["width"] + 2, metrics
    assert metrics["form"]["scrollWidth"] <= metrics["form"]["clientWidth"] + 2, metrics
    assert not metrics["clippedControls"], metrics
    assert not metrics["undersizedControls"], metrics
    page_errors = [err for err in page_errors if "localStorage" not in err]
    assert not page_errors, page_errors

    page.close()
    context.close()
