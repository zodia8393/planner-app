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
ORIGIN = {"origin": "http://testserver", "host": "testserver"}
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


def _app_css(app_name: str) -> str:
    return (ROOT / app_name / "static" / "css" / "app.css").read_text(encoding="utf-8")


def _can_launch_chromium() -> bool:
    if sync_playwright is None:
        return False
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(timeout=3000)
            browser.close()
    except Exception:
        return False
    return True


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


def _inline_render_css(app_name: str, html: str) -> str:
    css = "\n".join(
        [
            (ROOT / app_name / "static" / "tailwind.css").read_text(encoding="utf-8"),
            _app_css(app_name),
            """
            *, *::before, *::after {
                animation: none !important;
                transition: none !important;
                caret-color: transparent !important;
            }
            """,
        ]
    )
    html = html.replace("</head>", f"<style>{css}</style></head>")
    return html


def _inline_edit_render_css(app_name: str, edit_html: str) -> str:
    css = "\n".join(
        [
            (ROOT / app_name / "static" / "tailwind.css").read_text(encoding="utf-8"),
            _app_css(app_name),
            """
            *, *::before, *::after {
                animation: none !important;
                transition: none !important;
                caret-color: transparent !important;
            }
            """,
        ]
    )
    return f"""
    <html>
      <head><style>{css}</style></head>
      <body style="background: var(--color-bg); color: var(--color-text);">
        <main id="mainContent">
          <section id="todoPage" class="p-4">{edit_html}</section>
        </main>
      </body>
    </html>
    """


def _insert_todo(mod, profile_id: int, app_name: str) -> int:
    title = f"{app_name} core focus ui {uuid4().hex[:10]}"
    with mod.get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM todos WHERE profile_id=?",
            (profile_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO todos (profile_id, title, description, priority, due_date, tags, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                title,
                "Temporary isolated item for keyboard focus-visible UI testing.",
                1,
                "2026-06-12",
                '["focus-ui"]',
                max_order + 1,
            ),
        )
        return int(cur.lastrowid)


async def _fetch_core_flow_html(app_name: str, app, mod) -> tuple[str, str, str, int]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"FocusVisible{uuid4().hex[:8]}"
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

        todo_id = _insert_todo(mod, profile_id, app_name)
        dashboard = await client.get("/")
        todos = await client.get("/todos")
        edit = await client.get(
            f"/todos/{todo_id}/edit",
            headers={**ORIGIN, "HX-Request": "true"},
        )

    assert dashboard.status_code == 200, f"{app_name}: dashboard status {dashboard.status_code}"
    assert todos.status_code == 200, f"{app_name}: /todos status {todos.status_code}"
    assert edit.status_code == 200, f"{app_name}: edit form status {edit.status_code}"
    assert f'id="todo-{todo_id}"' in todos.text
    assert f'id="editTodoForm-{todo_id}"' in edit.text
    return dashboard.text, todos.text, edit.text, todo_id


def _focus_by_tab(page, selector: str, label: str, max_tabs: int = 90) -> None:
    assert page.locator(selector).count() >= 1, f"missing focus target: {label}"
    page.locator("body").evaluate(
        """(body) => {
            body.setAttribute('tabindex', '-1');
            body.focus();
        }"""
    )
    for _ in range(max_tabs):
        page.keyboard.press("Tab")
        if page.evaluate(
            "(selector) => document.activeElement && document.activeElement.matches(selector)",
            selector,
        ):
            return
    active = page.evaluate(
        """() => ({
            tag: document.activeElement?.tagName || '',
            id: document.activeElement?.id || '',
            text: document.activeElement?.textContent?.trim().slice(0, 80) || '',
            ariaLabel: document.activeElement?.getAttribute('aria-label') || '',
            href: document.activeElement?.getAttribute('href') || '',
        })"""
    )
    raise AssertionError(f"could not reach {label} with Tab; active={active}")


def _assert_visible_focus_indicator(page, selector: str, label: str) -> None:
    indicator = page.locator(selector).first.evaluate(
        """(el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            const outlineWidth = Number.parseFloat(style.outlineWidth) || 0;
            const outlineVisible = outlineWidth >= 2 &&
                style.outlineStyle !== 'none' &&
                style.outlineColor !== 'rgba(0, 0, 0, 0)' &&
                style.outlineColor !== 'transparent';
            const shadowVisible = style.boxShadow &&
                style.boxShadow !== 'none' &&
                !style.boxShadow.includes('rgba(0, 0, 0, 0)');
            return {
                outlineWidth,
                outlineStyle: style.outlineStyle,
                outlineColor: style.outlineColor,
                outlineOffset: Number.parseFloat(style.outlineOffset) || 0,
                boxShadow: style.boxShadow,
                rect: {
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    top: Math.round(rect.top),
                    left: Math.round(rect.left),
                },
                isFocusVisible: el.matches(':focus-visible'),
                hasVisibleFocusIndicator: outlineVisible || shadowVisible,
            };
        }"""
    )
    assert indicator["isFocusVisible"], f"{label}: target is focused but not :focus-visible"
    assert indicator["hasVisibleFocusIndicator"], f"{label}: missing visible indicator {indicator}"
    assert indicator["rect"]["width"] >= 12 and indicator["rect"]["height"] >= 12, (
        f"{label}: focused target is too small or hidden {indicator}"
    )
    assert indicator["outlineOffset"] >= 2 or indicator["boxShadow"] != "none", (
        f"{label}: focus ring is not visually separated {indicator}"
    )


def test_jm_my_dashboard_keyboard_focus_styles_are_visible():
    required_selectors = [
        ":where(\n  a[href],\n  button,\n  summary,\n  [role=\"button\"],\n  [tabindex]:not([tabindex=\"-1\"])\n ):focus-visible",
        ".dashboard-quick-actions :where(a[href], button):focus-visible",
        "#dashboard-empty-state :where(a[href], button):focus-visible",
        "#dashboardGrid :where(a[href], button, summary, [role=\"button\"], [tabindex]:not([tabindex=\"-1\"])):focus-visible",
        ".common-app-header :where(a[href], button, summary, [role=\"button\"], [tabindex]:not([tabindex=\"-1\"])):focus-visible",
        "#sidebar :where(a[href], button, summary, [role=\"button\"], [tabindex]:not([tabindex=\"-1\"])):focus-visible",
        "#mobileTabBar :where(a[href], button, [role=\"button\"], [tabindex]:not([tabindex=\"-1\"])):focus-visible",
    ]
    required_declarations = [
        "outline: 3px solid var(--color-accent);",
        "outline-offset: 3px;",
        "box-shadow: 0 0 0 5px var(--color-accent-soft);",
    ]

    for app_name in ("jm", "my"):
        css = _app_css(app_name)
        for selector in required_selectors:
            assert selector in css, f"{app_name}: missing focus selector {selector}"
        for declaration in required_declarations:
            assert declaration in css, f"{app_name}: missing visible focus declaration {declaration}"


def test_jm_my_todo_edit_save_and_cancel_focus_styles_are_distinct():
    required_selectors = [
        '#todoPage .todo-edit-actions [data-action="cancel-edit"]:focus-visible',
        '#todoPage .todo-edit-actions button[form^="editTodoForm-"][type="submit"]:focus-visible',
    ]
    cancel_declarations = [
        "outline: 3px solid var(--color-text-muted);",
        "border-color: var(--color-text-muted) !important;",
        "box-shadow: 0 0 0 5px rgba(87, 83, 78, 0.18);",
    ]
    save_declarations = [
        "outline: 3px solid var(--color-accent);",
        "box-shadow: 0 0 0 5px var(--color-accent-soft), var(--shadow-btn-accent);",
    ]

    for app_name in ("jm", "my"):
        css = _app_css(app_name)
        for selector in required_selectors:
            assert selector in css, f"{app_name}: missing todo edit focus selector {selector}"
        for declaration in cancel_declarations:
            assert declaration in css, f"{app_name}: missing cancel focus declaration {declaration}"
        for declaration in save_declarations:
            assert declaration in css, f"{app_name}: missing save focus declaration {declaration}"


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_core_todo_input_save_cancel_focus_visible_ui_contract(app_name, app, mod):
    _, todos_html, edit_html, todo_id = run_async(
        _fetch_core_flow_html(app_name, app, mod)
    )
    css = _app_css(app_name)

    create_focus_targets = [
        'id="newTodoTitle" type="text" name="title"',
        'class="input-premium flex-1 px-3.5 py-2.5 text-sm"',
        'type="submit" class="todo-create-submit btn-accent',
        'type="reset" class="todo-create-cancel',
        'aria-label="할일 추가 취소"',
    ]
    edit_focus_targets = [
        f'id="todo-edit-title-{todo_id}" type="text" name="title"',
        'class="w-full px-4 py-2.5 text-sm border rounded-lg focus-accent"',
        'textarea name="description"',
        'class="w-full px-4 py-2 text-sm border rounded-lg focus-accent"',
        'data-action="cancel-edit" class="todo-edit-action px-4 py-2 text-sm hover-text rounded-lg hover-surface"',
        f'type="submit" form="editTodoForm-{todo_id}"',
        'class="todo-edit-action px-5 py-2 btn-primary font-medium text-sm rounded-lg transition-colors"',
    ]
    focus_css_contract = [
        "input:focus-visible, select:focus-visible, textarea:focus-visible",
        "#todoPage #addForm .todo-create-submit:focus-visible",
        "#todoPage #addForm .todo-create-cancel:focus-visible",
        '#todoPage .todo-edit-actions [data-action="cancel-edit"]:focus-visible',
        '#todoPage .todo-edit-actions button[form^="editTodoForm-"][type="submit"]:focus-visible',
        "outline: 3px solid var(--color-accent);",
        "outline: 3px solid var(--color-text-muted);",
        "box-shadow: 0 0 0 5px var(--color-accent-soft), var(--shadow-btn-accent);",
        "box-shadow: 0 0 0 5px rgba(87, 83, 78, 0.18);",
    ]

    for target in create_focus_targets:
        assert target in todos_html, f"{app_name}: missing create focus target {target}"
    for target in edit_focus_targets:
        assert target in edit_html, f"{app_name}: missing edit focus target {target}"
    for contract in focus_css_contract:
        assert contract in css, f"{app_name}: missing visible focus CSS contract {contract}"


@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
@pytest.mark.parametrize("viewport_name,viewport", VIEWPORTS.items())
def test_core_flow_inputs_and_save_cancel_controls_show_visible_keyboard_focus(
    optional_chromium_browser,
    viewport_name,
    viewport,
    app_name,
    app,
    mod,
):
    if optional_chromium_browser is None:
        pytest.skip("Playwright Chromium is not available in this environment")

    dashboard_html, todos_html, edit_html, todo_id = run_async(
        _fetch_core_flow_html(app_name, app, mod)
    )
    context = optional_chromium_browser.new_context(
        viewport=viewport,
        device_scale_factor=1,
        is_mobile=viewport_name == "mobile",
        has_touch=viewport_name == "mobile",
    )
    page = context.new_page()
    try:
        page.set_content(_inline_render_css(app_name, dashboard_html), wait_until="load")
        dashboard_target = 'a[href="/todos#new"][aria-label="할일 추가 화면으로 이동"]'
        _focus_by_tab(
            page,
            dashboard_target,
            f"{app_name} {viewport_name} dashboard core todo entry link",
        )
        _assert_visible_focus_indicator(
            page,
            dashboard_target,
            f"{app_name} {viewport_name} dashboard core todo entry link",
        )

        page.set_content(_inline_render_css(app_name, todos_html), wait_until="load")
        create_title_target = "#addTodoForm #newTodoTitle"
        create_target = "#addTodoForm .todo-create-submit"
        create_cancel_target = '#addTodoForm .todo-create-cancel[type="reset"]'
        edit_target = f'#todo-{todo_id} button[hx-get="/todos/{todo_id}/edit"]'
        for selector, label in [
            (create_title_target, "todo create title input"),
            (create_target, "todo create submit button"),
            (create_cancel_target, "todo create cancel button"),
            (edit_target, "existing todo edit button"),
        ]:
            _focus_by_tab(page, selector, f"{app_name} {viewport_name} {label}")
            _assert_visible_focus_indicator(
                page,
                selector,
                f"{app_name} {viewport_name} {label}",
            )

        page.set_content(_inline_edit_render_css(app_name, edit_html), wait_until="load")
        edit_title_target = f"#todo-edit-title-{todo_id}"
        edit_description_target = f'#editTodoForm-{todo_id} textarea[name="description"]'
        edit_cancel_target = f'#todo-{todo_id} .todo-edit-actions [data-action="cancel-edit"]'
        save_target = f'button[form="editTodoForm-{todo_id}"][type="submit"]'
        for selector, label in [
            (edit_title_target, "edit title input"),
            (edit_description_target, "edit description textarea"),
            (edit_cancel_target, "edit cancel control"),
            (save_target, "edit save button"),
        ]:
            _focus_by_tab(page, selector, f"{app_name} {viewport_name} {label}")
            _assert_visible_focus_indicator(
                page,
                selector,
                f"{app_name} {viewport_name} {label}",
            )
    finally:
        context.close()
