"""
Independent 390x844 UI checks for jm/my todo edit/save touch controls.

The apps render against isolated temporary databases from conftest.py. The test
creates and saves only temporary fixture data, not production user data.
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


def _insert_edit_touch_todo(mod, profile_id: int, app_name: str) -> int:
    title = f"{app_name} mobile edit save touch controls {uuid4().hex[:10]}"
    with mod.get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM todos WHERE profile_id=?",
            (profile_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO todos (
                profile_id, title, description, priority, due_date, repeat_type,
                tags, energy_level, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                title,
                "Mobile 390 edit save touch target verification item.",
                2,
                "2026-06-12",
                "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE;COUNT=10",
                '["mvp-mobile-edit-touch"]',
                3,
                max_order + 1,
            ),
        )
        todo_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO subtasks (todo_id, title, sort_order) VALUES (?, ?, ?)",
            (todo_id, "Confirm edit save controls are touch sized", 1),
        )
        return todo_id


async def _fetch_and_save_core_todo_edit(app_name: str, app, mod) -> tuple[str, str, int]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"EditTouch{uuid4().hex[:8]}"
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

        todo_id = _insert_edit_touch_todo(mod, profile_id, app_name)

        list_response = await client.get("/todos")
        assert list_response.status_code == 200, f"{app_name} /todos: {list_response.status_code}"
        assert f'id="todo-{todo_id}"' in list_response.text

        edit_response = await client.get(
            f"/todos/{todo_id}/edit",
            headers={**ORIGIN, "HX-Request": "true"},
        )
        assert edit_response.status_code == 200, (
            f"{app_name} /todos/{todo_id}/edit: {edit_response.status_code}"
        )
        assert f'id="editTodoForm-{todo_id}"' in edit_response.text

        saved = await client.put(
            f"/todos/{todo_id}",
            data={
                "title": f"{app_name} mobile edit saved touch controls {uuid4().hex[:10]}",
                "description": "Saved through the mobile edit/save touch-control flow.",
                "due_date": "2026-06-13",
                "priority": "3",
                "tags": "mvp-mobile-edit-touch, saved",
                "energy_level": "1",
            },
            headers={**ORIGIN, "HX-Request": "true"},
        )
        assert saved.status_code == 200, f"{app_name} /todos/{todo_id} PUT: {saved.status_code}"
        assert "변경사항이 저장되었습니다." in saved.text

        return list_response.text, edit_response.text, todo_id


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


def _assert_static_edit_touch_contract(app_name: str, edit_html: str, todo_id: int) -> None:
    template = _asset_text(app_name, "templates/partials/todo_edit_form.html")
    app_css = _asset_text(app_name, "static/css/app.css")

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}
    assert f'id="editTodoForm-{todo_id}"' in edit_html
    assert f'hx-put="/todos/{todo_id}"' in edit_html
    assert f'form="editTodoForm-{todo_id}"' in edit_html
    assert 'aria-label="알림 추가"' in edit_html
    assert 'aria-label="서브태스크 토글"' in edit_html
    assert 'aria-label="하위 작업 추가"' in edit_html
    assert "저장" in edit_html
    assert "취소" in edit_html

    assert 'class="todo-edit-action text-xs hover-text"' in template
    assert 'class="todo-edit-action px-2.5 py-1 text-xs btn-primary rounded-lg"' in template
    assert 'class="todo-edit-action flex-shrink-0 w-4 h-4 rounded border flex items-center justify-center transition-colors"' in template
    assert 'class="todo-edit-actions flex flex-wrap justify-end gap-2 mt-3"' in template
    assert 'class="todo-edit-action px-4 py-2 text-sm hover-text rounded-lg hover-surface"' in template
    assert 'class="todo-edit-action px-5 py-2 btn-primary font-medium text-sm rounded-lg transition-colors"' in template

    assert "@media (max-width: 640px)" in app_css
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert '#todoPage :where([id^="editTodoForm-"] input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), [id^="editTodoForm-"] select, [id^="editTodoForm-"] textarea, [id^="editTodoForm-"] button, .todo-edit-action)' in app_css
    assert "min-height: 2.75rem;" in app_css
    assert '#todoPage :where([id^="editTodoForm-"] button, .todo-edit-action)' in app_css
    assert "min-width: 2.75rem;" in app_css
    assert "#todoPage .todo-edit-actions" in app_css
    assert "flex-wrap: wrap;" in app_css


def _edit_touch_metrics(page, todo_id: int):
    return page.evaluate(
        """(todoId) => {
            const viewportWidth = window.innerWidth;
            const card = document.querySelector(`#todo-${todoId}`);
            const actionRow = document.querySelector(`#todo-${todoId} .todo-edit-actions`);
            const selectors = [
                `#editTodoForm-${todoId} input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])`,
                `#editTodoForm-${todoId} select`,
                `#editTodoForm-${todoId} textarea`,
                `#editTodoForm-${todoId} button`,
                `#todo-${todoId} .todo-edit-action`
            ].join(',');
            const controls = Array.from(document.querySelectorAll(selectors))
                .filter((el, index, all) => all.indexOf(el) === index)
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 1
                        && rect.height > 1;
                })
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    const label = el.getAttribute('aria-label')
                        || el.getAttribute('name')
                        || el.textContent.trim().replace(/\\s+/g, ' ');
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        label,
                        left: Math.round(rect.left),
                        right: Math.round(rect.right),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                    };
                });
            const cardRect = card.getBoundingClientRect();
            const rowRect = actionRow.getBoundingClientRect();
            return {
                viewportWidth,
                documentScrollWidth: document.documentElement.scrollWidth,
                bodyScrollWidth: document.body.scrollWidth,
                card: {
                    left: Math.round(cardRect.left),
                    right: Math.round(cardRect.right),
                    width: Math.round(cardRect.width),
                    scrollWidth: card.scrollWidth,
                    clientWidth: card.clientWidth,
                },
                actionRow: {
                    left: Math.round(rowRect.left),
                    right: Math.round(rowRect.right),
                    width: Math.round(rowRect.width),
                    scrollWidth: actionRow.scrollWidth,
                    clientWidth: actionRow.clientWidth,
                },
                controlCount: controls.length,
                clippedControls: controls.filter((control) =>
                    control.left < cardRect.left - 2
                    || control.right > cardRect.right + 2
                    || control.left < -2
                    || control.right > viewportWidth + 2
                ),
                undersizedControls: controls.filter((control) =>
                    control.height < 44
                    || ((control.tag === 'button' || control.tag === 'a') && control.width < 44)
                ),
                missingLabels: controls.filter((control) => !control.label),
            };
        }""",
        todo_id,
    )


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_todo_edit_save_mobile_390_touch_controls_are_visible_contained_and_sized(
    optional_chromium_browser, app_name, app, mod
):
    list_html, edit_html, todo_id = run_async(
        _fetch_and_save_core_todo_edit(app_name, app, mod)
    )
    _assert_static_edit_touch_contract(app_name, edit_html, todo_id)

    if optional_chromium_browser is None:
        return

    html = _inline_render_css(app_name, list_html)
    context = optional_chromium_browser.new_context(
        viewport=MOBILE_VIEWPORT,
        java_script_enabled=False,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda err, _errors=page_errors: _errors.append(str(err)))
    page.set_content(html, wait_until="domcontentloaded", timeout=10000)
    page.locator(f"#todo-{todo_id}").evaluate(
        "(element, editHtml) => { element.outerHTML = editHtml; }",
        edit_html,
    )
    page.wait_for_timeout(100)

    metrics = _edit_touch_metrics(page, todo_id)
    assert metrics["viewportWidth"] == MOBILE_VIEWPORT["width"], metrics
    assert metrics["controlCount"] >= 14, metrics
    assert metrics["documentScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, metrics
    assert metrics["bodyScrollWidth"] <= MOBILE_VIEWPORT["width"] + 2, metrics
    assert metrics["card"]["right"] <= MOBILE_VIEWPORT["width"] + 2, metrics
    assert metrics["card"]["scrollWidth"] <= metrics["card"]["clientWidth"] + 2, metrics
    assert metrics["actionRow"]["right"] <= MOBILE_VIEWPORT["width"] + 2, metrics
    assert metrics["actionRow"]["scrollWidth"] <= metrics["actionRow"]["clientWidth"] + 2, metrics
    assert not metrics["clippedControls"], metrics
    assert not metrics["undersizedControls"], metrics
    assert not metrics["missingLabels"], metrics
    page_errors = [err for err in page_errors if "localStorage" not in err]
    assert not page_errors, page_errors

    page.close()
    context.close()
