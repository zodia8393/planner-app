"""Independent 390x844 mobile containment contracts for jm/my todo editing."""

from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from conftest import jm_mod, my_mod


ROOT = Path(__file__).resolve().parents[1]
MOBILE_VIEWPORT = {"width": 390, "height": 844}
ORIGIN = {"origin": "http://test", "host": "test"}


def _insert_mobile_edit_todo(mod, profile_id: int, title: str) -> int:
    with mod.get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM todos WHERE profile_id=?",
            (profile_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO todos (
                profile_id, title, description, priority, due_date, repeat_type,
                tags, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                title,
                "Mobile edit responsive verification item.",
                2,
                "2026-06-12",
                "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE;COUNT=10",
                '["mvp-mobile-edit"]',
                max_order + 1,
            ),
        )
        return int(cur.lastrowid)


async def _setup_my_profile(client: httpx.AsyncClient, name: str) -> int:
    response = await client.post(
        "/setup",
        data={"name": name},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303

    with my_mod.get_db() as conn:
        row = conn.execute("SELECT id FROM profiles WHERE name=?", (name,)).fetchone()
    assert row is not None
    return int(row["id"])


async def _fetch_edit_flow_html(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    app_name: str,
) -> tuple[str, str, int]:
    todo_id = _insert_mobile_edit_todo(
        mod,
        profile_id,
        f"{app_name} mobile edit responsive todo {uuid4().hex}",
    )

    list_response = await client.get("/todos")
    assert list_response.status_code == 200
    assert f'id="todo-{todo_id}"' in list_response.text

    edit_response = await client.get(
        f"/todos/{todo_id}/edit",
        headers={**ORIGIN, "HX-Request": "true"},
    )
    assert edit_response.status_code == 200
    return list_response.text, edit_response.text, todo_id


def _assert_mobile_edit_no_horizontal_scroll_contract(
    app_name: str,
    list_html: str,
    edit_html: str,
    todo_id: int,
) -> None:
    base = (ROOT / app_name / "templates" / "base.html").read_text(encoding="utf-8")
    app_css = (ROOT / app_name / "static" / "css" / "app.css").read_text(
        encoding="utf-8"
    )

    assert MOBILE_VIEWPORT == {"width": 390, "height": 844}

    # Document and primary containers must prevent accidental page-level overflow.
    assert 'role="main"' in base
    assert 'id="mainContent"' in base
    assert "mobile-pad-bottom" in base
    assert "*, *::before, *::after { box-sizing: border-box; }" in app_css
    assert "html, body { overflow-x: hidden; }" in app_css
    assert "main { overflow-x: hidden; }" in app_css
    assert "#mainContent { overflow: hidden; }" in app_css
    assert "#mainContent {" in app_css
    assert "max-width: 100%" in app_css
    assert "min-width: 0" in app_css
    assert "overflow-wrap: anywhere" in app_css

    # The selected MVP edit surface is the HTMX edit form inside the core /todos list.
    assert 'id="todoList"' in list_html
    assert f'id="todo-{todo_id}"' in list_html
    assert f'id="todo-{todo_id}"' in edit_html
    assert f'id="editTodoForm-{todo_id}"' in edit_html
    assert f'hx-put="/todos/{todo_id}"' in edit_html
    assert 'aria-label="할일 제목"' in edit_html
    assert 'aria-label="설명"' in edit_html
    assert 'aria-label="마감일"' in edit_html
    assert 'aria-label="우선순위"' in edit_html
    assert 'aria-label="알림 시간 선택"' in edit_html
    assert 'form="editTodoForm-' in edit_html
    assert "저장" in edit_html

    # Main edit rows and controls must wrap or shrink inside a 390px viewport.
    assert 'class="flex flex-wrap items-center justify-between gap-2 mb-2"' in edit_html
    assert 'class="flex flex-wrap gap-2 min-w-0"' in edit_html
    assert 'class="flex flex-wrap items-center gap-2 min-w-0"' in edit_html
    assert 'class="flex flex-wrap gap-1.5 min-w-0"' in edit_html
    assert 'class="flex-1 min-w-0 px-2 py-1.5 text-xs border rounded-lg focus-accent"' in edit_html
    assert 'class="flex flex-wrap gap-1 min-w-0"' in edit_html
    assert 'class="flex-1 min-w-0 px-2 py-1 text-xs border rounded focus-accent"' in edit_html
    assert 'class="todo-edit-actions flex flex-wrap justify-end gap-2 mt-3"' in edit_html

    assert "#mainContent :where(.work-card, details, section, article, form, table)" in app_css
    assert "#mainContent :where(button, a, .btn-accent" in app_css
    assert "input, select, textarea { max-width: 100%; box-sizing: border-box; }" in app_css
    assert "form { max-width: 100%; }" in app_css
    assert ".flex { min-width: 0; }" in app_css
    assert ".flex > * { min-width: 0; }" in app_css
    assert "@media (max-width: 640px)" in app_css
    assert "#mainContent :where(.work-card input:not([type=\"checkbox\"]):not([type=\"radio\"]), .work-card select, .work-card textarea)" in app_css


@pytest.mark.asyncio
async def test_jm_todo_edit_save_mobile_390_has_no_document_or_container_overflow_contract(
    jm: httpx.AsyncClient,
):
    list_html, edit_html, todo_id = await _fetch_edit_flow_html(jm, jm_mod, 1, "jm")

    _assert_mobile_edit_no_horizontal_scroll_contract(
        "jm", list_html, edit_html, todo_id
    )


@pytest.mark.asyncio
async def test_my_todo_edit_save_mobile_390_has_no_document_or_container_overflow_contract(
    my: httpx.AsyncClient,
):
    profile_id = await _setup_my_profile(my, f"MobileEdit{uuid4().hex[:10]}")
    list_html, edit_html, todo_id = await _fetch_edit_flow_html(
        my, my_mod, profile_id, "my"
    )

    _assert_mobile_edit_no_horizontal_scroll_contract(
        "my", list_html, edit_html, todo_id
    )
