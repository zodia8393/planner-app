"""Accessible-name checks for jm/my MVP button surfaces.

The apps are imported through conftest.py with isolated temp databases, so these
tests do not touch production planner data.
"""

from html.parser import HTMLParser
from uuid import uuid4

import httpx
import pytest

from conftest import jm_app, jm_mod, my_app, my_mod


ORIGIN = {"origin": "http://testserver", "host": "testserver"}


class ButtonNameParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.buttons: list[dict] = []
        self.labels_by_id: dict[str, str] = {}
        self._button_stack: list[dict] = []
        self._label_stack: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        raw = self.get_starttag_text() or ""

        if tag == "label":
            self._label_stack.append({"id": attr.get("id", ""), "text": []})

        if tag == "img":
            alt = attr.get("alt", "")
            if alt:
                for button in self._button_stack:
                    button["img_alts"].append(alt)

        if tag == "svg":
            for button in self._button_stack:
                button["svg_count"] += 1

        if tag == "button" or attr.get("role") == "button":
            button = {
                "attrs": attr,
                "text": [],
                "img_alts": [],
                "svg_count": 0,
                "html": raw,
            }
            self.buttons.append(button)
            self._button_stack.append(button)

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        for button in self._button_stack:
            button["text"].append(data)
        if self._label_stack:
            self._label_stack[-1]["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_stack:
            label = self._label_stack.pop()
            if label["id"]:
                self.labels_by_id[label["id"]] = _squash(" ".join(label["text"]))

        if tag == "button" and self._button_stack:
            self._button_stack.pop()


def _squash(value: str) -> str:
    return " ".join(value.split())


def _button_text(button: dict) -> str:
    return _squash(" ".join(button["text"]))


def _button_name(button: dict, labels_by_id: dict[str, str]) -> str:
    return _squash(" ".join(_button_name_candidates(button, labels_by_id, include_content=True)))


def _explicit_button_name(button: dict, labels_by_id: dict[str, str]) -> str:
    return _squash(" ".join(_button_name_candidates(button, labels_by_id, include_content=False)))


def _button_name_candidates(button: dict, labels_by_id: dict[str, str], include_content: bool) -> list[str]:
    attrs = button["attrs"]
    candidates = []

    if attrs.get("aria-label", "").strip():
        candidates.append(attrs["aria-label"])

    labelledby = attrs.get("aria-labelledby", "")
    for label_id in labelledby.split():
        if labels_by_id.get(label_id):
            candidates.append(labels_by_id[label_id])

    if attrs.get("title", "").strip():
        candidates.append(attrs["title"])

    if include_content:
        candidates.append(_button_text(button))
        candidates.extend(button["img_alts"])

    return [candidate for candidate in candidates if candidate]


def _is_icon_only_button(button: dict) -> bool:
    text = _button_text(button)
    symbol_texts = {"+", "-", "−", "×", "x", "X", "✕", "✖", "…", "...", "⋯", "≡", "☰"}
    has_icon_content = bool(button["svg_count"] or button["img_alts"] or text in symbol_texts)
    has_meaningful_visible_text = bool(text and text not in symbol_texts)
    return has_icon_content and not has_meaningful_visible_text


def _is_hidden_or_disabled(button: dict) -> bool:
    attrs = button["attrs"]
    if "disabled" in attrs or attrs.get("aria-hidden") == "true":
        return True
    classes = set(attrs.get("class", "").split())
    return bool({"hidden", "sr-only"} & classes)


def _button_summary(button: dict) -> dict[str, str]:
    attrs = button["attrs"]
    return {
        "id": attrs.get("id", ""),
        "type": attrs.get("type", ""),
        "aria-label": attrs.get("aria-label", ""),
        "aria-labelledby": attrs.get("aria-labelledby", ""),
        "title": attrs.get("title", ""),
        "text": _button_text(button),
        "img_alt": _squash(" ".join(button["img_alts"])),
        "svg_count": str(button["svg_count"]),
        "html": button["html"][:180].replace("\n", " "),
    }


def _assert_text_or_image_buttons_have_names(app_name: str, route: str, html: str) -> None:
    parser = ButtonNameParser()
    parser.feed(html)

    offenders = []
    for button in parser.buttons:
        if _is_hidden_or_disabled(button):
            continue
        has_text_or_alt = bool(_button_text(button) or button["img_alts"])
        if has_text_or_alt and not _button_name(button, parser.labels_by_id):
            offenders.append(_button_summary(button))

    assert not offenders, f"{app_name} {route}: text/image buttons without accessible names: {offenders}"


def _assert_icon_only_buttons_have_explicit_names(app_name: str, route: str, html: str) -> None:
    parser = ButtonNameParser()
    parser.feed(html)

    offenders = []
    for button in parser.buttons:
        if _is_hidden_or_disabled(button):
            continue
        if _is_icon_only_button(button) and not _explicit_button_name(button, parser.labels_by_id):
            offenders.append(_button_summary(button))

    assert not offenders, f"{app_name} {route}: icon-only buttons without explicit accessible names: {offenders}"


async def _setup_my_profile(client: httpx.AsyncClient) -> int:
    name = f"ButtonA11y{uuid4().hex[:8]}"
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


def _insert_todo(mod, profile_id: int, title: str) -> int:
    with mod.get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO todos (profile_id, title, description, priority, due_date, tags, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                title,
                "Temporary isolated test item for accessible-name rendering.",
                2,
                "2026-06-12",
                '["button-a11y"]',
                1,
            ),
        )
        return int(cur.lastrowid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app_name,app,mod",
    [
        ("jm", jm_app, jm_mod),
        ("my", my_app, my_mod),
    ],
)
async def test_jm_my_mvp_text_or_image_buttons_have_accessible_names(app_name, app, mod):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_id = await _setup_my_profile(client)

        for route in ("/", "/todos"):
            response = await client.get(route)
            assert response.status_code == 200, f"{app_name} {route}: status {response.status_code}"
            _assert_text_or_image_buttons_have_names(app_name, route, response.text)
            _assert_icon_only_buttons_have_explicit_names(app_name, route, response.text)

        todo_id = _insert_todo(mod, profile_id, f"Button accessible name {uuid4().hex[:8]}")
        response = await client.get(f"/todos/{todo_id}/edit")
        assert response.status_code == 200, f"{app_name} /todos/{todo_id}/edit: status {response.status_code}"
        _assert_text_or_image_buttons_have_names(app_name, "/todos/{id}/edit", response.text)
        _assert_icon_only_buttons_have_explicit_names(app_name, "/todos/{id}/edit", response.text)
