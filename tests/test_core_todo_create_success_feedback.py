import re
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from conftest import jm_mod, my_mod


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = {"origin": "http://test", "host": "test"}
HX_HEADERS = {
    **ORIGIN,
    "HX-Request": "true",
    "HX-Current-URL": "http://test/todos",
}


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


def _css_tokens(app_name: str) -> dict[str, str]:
    css = (ROOT / app_name / "static/css/app.css").read_text(encoding="utf-8")
    root_match = re.search(r":root\s*\{(?P<body>.*?)\n\s*\}", css, re.S)
    assert root_match, f"{app_name}: missing :root design tokens"
    return {
        name: value.lower()
        for name, value in re.findall(
            r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;",
            root_match.group("body"),
        )
    }


def _assert_create_feedback_visual_contract(app_name: str, html: str) -> None:
    css = (ROOT / app_name / "static/css/app.css").read_text(encoding="utf-8")
    assert 'class="todo-create-feedback mb-3 rounded-lg border px-3 py-2 text-sm font-medium"' in html
    assert ".todo-create-feedback {\n  background: var(--color-success-soft);" in css
    assert "color: var(--color-success);" in css
    assert ".todo-create-error {\n  background: var(--color-danger-soft);" in css
    assert ".todo-create-loading.htmx-indicator {" in css
    assert "background: var(--color-info-soft);" in css

    tokens = _css_tokens(app_name)
    status_pairs = [
        ("--color-success", "--color-success-soft"),
        ("--color-danger", "--color-danger-soft"),
        ("--color-info", "--color-info-soft"),
    ]
    for foreground, background in status_pairs:
        ratio = _contrast_ratio(tokens[foreground], tokens[background])
        assert ratio >= 4.5, (
            f"{app_name}: {foreground} on {background} contrast {ratio:.2f} < 4.5"
        )


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


def _delete_todo_by_title(mod, profile_id: int, title: str) -> None:
    with mod.get_db() as conn:
        conn.execute(
            "DELETE FROM todos WHERE profile_id=? AND title=?",
            (profile_id, title),
        )


def _fetch_todo_by_title(mod, profile_id: int, title: str):
    with mod.get_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM todos
            WHERE profile_id=? AND title=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (profile_id, title),
        ).fetchone()


def _assert_keyboard_visible_success_feedback(html: str) -> None:
    feedback_index = html.index('id="todo-create-feedback"')
    input_index = html.index('id="newTodoTitle"')

    assert feedback_index < input_index
    assert 'id="todo-create-feedback"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert "할일이 추가되었습니다." in html


def _assert_created_todo_reflected_in_list(html: str, todo_id: int, title: str) -> None:
    assert 'aria-label="할일 목록"' in html
    assert 'id="todoList"' in html
    assert f'id="todo-{todo_id}"' in html
    assert title in html
    assert f'hx-get="/todos/{todo_id}/edit"' in html


async def _assert_hx_create_success_feedback(
    client: httpx.AsyncClient,
    mod,
    profile_id: int,
    instance_label: str,
) -> None:
    title = f"{instance_label} hx create feedback {uuid4().hex}"

    try:
        created = await client.post(
            "/todos",
            data={"title": title},
            headers=HX_HEADERS,
            follow_redirects=False,
        )

        assert created.status_code == 200
        assert created.headers["hx-redirect"] == "/todos"
        assert "todo_flash=created" in created.headers["set-cookie"]

        row = _fetch_todo_by_title(mod, profile_id, title)
        assert row is not None

        redirected = await client.get("/todos")
        assert redirected.status_code == 200
        _assert_keyboard_visible_success_feedback(redirected.text)
        _assert_create_feedback_visual_contract(instance_label, redirected.text)
        _assert_created_todo_reflected_in_list(redirected.text, int(row["id"]), title)

        refreshed = await client.get("/todos")
        assert refreshed.status_code == 200
        assert 'id="todo-create-feedback"' not in refreshed.text
    finally:
        _delete_todo_by_title(mod, profile_id, title)


@pytest.mark.asyncio
async def test_jm_hx_create_success_feedback_is_visible_after_redirect(jm: httpx.AsyncClient):
    await _assert_hx_create_success_feedback(jm, jm_mod, 1, "jm")


@pytest.mark.asyncio
async def test_my_hx_create_success_feedback_is_visible_after_redirect(my: httpx.AsyncClient):
    profile_id = await _setup_my_profile(my, f"MvpCreateFeedback{uuid4().hex[:10]}")

    await _assert_hx_create_success_feedback(my, my_mod, profile_id, "my")
