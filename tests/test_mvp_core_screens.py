from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "mvp_core_screens.md"
ORIGIN = {"origin": "http://test", "host": "test"}


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._current = {key: value or "" for key, value in attrs}
        self._current["text"] = ""

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None:
            self._current["text"] = " ".join(self._current["text"].split())
            self.anchors.append(self._current)
            self._current = None


async def _setup_my_profile(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/setup",
        data={"name": f"Mvp{uuid4().hex[:8]}"},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303


def _core_entry_href(html: str) -> str:
    parser = _AnchorCollector()
    parser.feed(html)
    matches = [
        anchor["href"]
        for anchor in parser.anchors
        if anchor.get("href") == "/todos#new" and "할일 추가" in anchor.get("text", "")
    ]

    assert matches == ["/todos#new"]
    return matches[0]


def _accessible_name(anchor: dict[str, str]) -> str:
    return (anchor.get("aria-label") or anchor.get("title") or anchor.get("text") or "").strip()


def _assert_keyboard_reachable_create_entry(html: str) -> None:
    parser = _AnchorCollector()
    parser.feed(html)

    matches = [
        anchor
        for anchor in parser.anchors
        if anchor.get("href") == "/todos#new"
        and "할일 추가" in _accessible_name(anchor)
    ]

    assert len(matches) == 1
    entry = matches[0]
    assert entry.get("tabindex", "0") != "-1"
    assert entry.get("aria-hidden") != "true"
    assert _accessible_name(entry) == "할일 추가 화면으로 이동"


def _route_without_fragment(href: str) -> str:
    parsed = urlsplit(href)
    return urlunsplit(("", "", parsed.path, parsed.query, ""))


def _assert_core_todo_screen(html: str) -> None:
    assert "업무 관리" in html
    assert 'id="addForm"' in html
    assert 'action="/todos"' in html
    assert 'aria-label="새 업무 제목"' in html


def _assert_hash_new_focus_contract(instance_name: str) -> None:
    script = (ROOT / instance_name / "static" / "js" / "todos.js").read_text(encoding="utf-8")

    assert "location.hash === '#new'" in script
    assert "document.querySelector('input[name=\"title\"]')" in script
    assert "ti.scrollIntoView({block:'center'})" in script
    assert "ti.focus()" in script


def test_jm_core_screen_is_documented():
    text = DOC.read_text(encoding="utf-8")

    assert "| jm | 할 일 목록 | `/todos` |" in text
    assert "대시보드 첫 빠른 실행 항목" in text
    assert "캘린더, 설정, 통계, 관리" in text


def test_my_core_screen_is_documented():
    text = DOC.read_text(encoding="utf-8")

    assert "| my | 할 일 목록 | `/todos` |" in text
    assert "대시보드 첫 빠른 실행 항목" in text
    assert "캘린더, 설정, 통계, 관리" in text


def test_jm_documented_core_screen_matches_dashboard_entry_points():
    dashboard = (ROOT / "jm" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    base = (ROOT / "jm" / "templates" / "base.html").read_text(encoding="utf-8")
    text = DOC.read_text(encoding="utf-8")

    assert "| jm | 할 일 목록 | `/todos` |" in text
    assert 'href="/todos#new"' in dashboard
    assert 'aria-label="할일 추가 화면으로 이동"' in dashboard
    assert 'href="/todos"' in base
    assert "할 일" in base
    _assert_hash_new_focus_contract("jm")


def test_my_documented_core_screen_matches_dashboard_entry_points():
    dashboard = (ROOT / "my" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    base = (ROOT / "my" / "templates" / "base.html").read_text(encoding="utf-8")
    text = DOC.read_text(encoding="utf-8")

    assert "| my | 할 일 목록 | `/todos` |" in text
    assert 'href="/todos#new"' in dashboard
    assert 'aria-label="할일 추가 화면으로 이동"' in dashboard
    assert 'href="/todos"' in base
    assert "할 일" in base
    _assert_hash_new_focus_contract("my")


@pytest.mark.asyncio
async def test_jm_dashboard_response_renders_core_list_entry_link(jm: httpx.AsyncClient):
    response = await jm.get("/")

    assert response.status_code == 200
    assert 'aria-label="빠른 작업"' in response.text
    assert 'href="/todos#new"' in response.text
    assert 'aria-label="할일 추가 화면으로 이동"' in response.text
    _assert_keyboard_reachable_create_entry(response.text)


@pytest.mark.asyncio
async def test_my_dashboard_response_renders_core_list_entry_link(my: httpx.AsyncClient):
    await _setup_my_profile(my)

    response = await my.get("/")

    assert response.status_code == 200
    assert 'aria-label="빠른 작업"' in response.text
    assert 'href="/todos#new"' in response.text
    assert 'aria-label="할일 추가 화면으로 이동"' in response.text
    _assert_keyboard_reachable_create_entry(response.text)


@pytest.mark.asyncio
async def test_jm_rendered_core_list_entry_href_routes_to_core_list(jm: httpx.AsyncClient):
    dashboard = await jm.get("/")
    assert dashboard.status_code == 200

    href = _core_entry_href(dashboard.text)
    response = await jm.get(_route_without_fragment(href))

    assert response.status_code == 200
    _assert_core_todo_screen(response.text)


@pytest.mark.asyncio
async def test_my_rendered_core_list_entry_href_routes_to_core_list(my: httpx.AsyncClient):
    await _setup_my_profile(my)
    dashboard = await my.get("/")
    assert dashboard.status_code == 200

    href = _core_entry_href(dashboard.text)
    response = await my.get(_route_without_fragment(href))

    assert response.status_code == 200
    _assert_core_todo_screen(response.text)
