from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = {"origin": "http://test", "host": "test"}


class _FocusableCollector(HTMLParser):
    FOCUSABLE_TAGS = {"a", "button", "input", "select", "textarea", "summary"}

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self._stack: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        attr["tag"] = tag
        attr["text"] = ""
        if tag == "input":
            if self._is_focusable(attr):
                self.items.append(attr)
            return
        self._stack.append(attr)

    def handle_data(self, data: str) -> None:
        for item in self._stack:
            item["text"] += data

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] != tag:
                continue
            item = self._stack.pop(index)
            if self._is_focusable(item):
                item["text"] = " ".join(item["text"].split())
                self.items.append(item)
            return

    def _is_focusable(self, item: dict[str, str]) -> bool:
        tag = item["tag"]
        if item.get("disabled") is not None and "disabled" in item:
            return False
        if tag == "input" and item.get("type") == "hidden":
            return False
        if item.get("tabindex") == "-1":
            return False
        return (
            tag in self.FOCUSABLE_TAGS
            or "href" in item
            or item.get("role") in {"button", "link"}
            or ("tabindex" in item and item.get("tabindex") != "-1")
        )


def _focusables(html: str) -> list[dict[str, str]]:
    parser = _FocusableCollector()
    parser.feed(html)
    return parser.items


def _label(item: dict[str, str]) -> str:
    return (
        item.get("aria-label")
        or item.get("title")
        or item.get("placeholder")
        or item.get("text")
        or item.get("name")
        or ""
    ).strip()


def _index(items: list[dict[str, str]], predicate) -> int:
    for index, item in enumerate(items):
        if predicate(item):
            return index
    raise AssertionError(f"focus target not found in {[(_label(item), item.get('href', ''), item.get('id', '')) for item in items]}")


async def _setup_my_profile(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/setup",
        data={"name": f"DashboardFocus{uuid4().hex[:8]}"},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303


def _assert_dashboard_focus_order(app_name: str, html: str) -> None:
    items = _focusables(html)
    assert items, f"{app_name}: dashboard rendered no keyboard focus targets"
    assert all(item.get("tabindex", "0") != "-1" for item in items)
    assert not [item for item in items if item.get("tabindex", "").isdigit() and item["tabindex"] != "0"]

    skip = _index(items, lambda item: item.get("href") == "#mainContent")
    nav_dashboard = _index(items, lambda item: item.get("href") == "/" and _label(item) == "대시보드")
    nav_todos = _index(items, lambda item: item.get("href") == "/todos" and _label(item) == "할 일")
    more = _index(items, lambda item: item["tag"] == "summary" and "더보기" in _label(item))
    settings = _index(items, lambda item: item.get("href") == "/settings" and _label(item) == "설정")
    theme = _index(items, lambda item: item.get("id") == "themeToggleBtn")
    sidebar_toggle = _index(items, lambda item: item.get("aria-controls") == "sidebar")
    notifications = _index(items, lambda item: item.get("aria-label") == "알림 패널 열기")
    usage = _index(items, lambda item: item["tag"] == "summary" and "사용법" in _label(item))
    quick_todo = _index(items, lambda item: item.get("href") == "/todos#new" and "할일 추가" in _label(item))
    quick_calendar = _index(items, lambda item: item.get("href") == "/calendar#new")
    quick_memo = _index(items, lambda item: item.get("href") == "/memos#new")
    focus_25 = _index(items, lambda item: item.get("aria-label") == "25분 집중 (추천)")
    quick_input = _index(items, lambda item: item.get("id") == "quickTitle")
    quick_submit = _index(items, lambda item: item["tag"] == "button" and _label(item) == "추가")
    mobile_dashboard = _index(
        items,
        lambda item: item.get("href") == "/" and _label(item) == "대시보드" and items.index(item) > quick_submit,
    )
    mobile_more = _index(items, lambda item: item.get("aria-label") == "더보기 메뉴")

    assert skip < nav_dashboard < nav_todos < more < settings < theme
    assert theme < sidebar_toggle < notifications < usage
    assert usage < quick_todo < quick_calendar < quick_memo < focus_25 < quick_input < quick_submit
    assert quick_submit < mobile_dashboard < mobile_more

    main_labels = [_label(item) for item in items[usage : quick_submit + 1]]
    assert "빠른 업무 추가" in main_labels
    assert "추가" in main_labels
    assert not [
        item
        for item in items
        if item["tag"] in {"a", "button", "input", "select", "textarea", "summary"} and not _label(item)
    ]


def _assert_sidebar_keyboard_script_contract(app_name: str) -> None:
    base = (ROOT / app_name / "templates" / "base.html").read_text(encoding="utf-8")
    script = (ROOT / app_name / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert 'aria-controls="sidebar"' in base
    assert 'aria-expanded="false"' in base
    assert "function syncSidebarAccessibility()" in script
    assert "window.matchMedia('(max-width: 1023px)').matches" in script
    assert "sb.setAttribute('inert', '')" in script
    assert "sb.setAttribute('aria-hidden', 'true')" in script
    assert "sb.removeAttribute('inert')" in script
    assert "btn.setAttribute('aria-expanded'" in script
    assert "first.focus()" in script
    assert "window.addEventListener('resize', syncSidebarAccessibility)" in script


class _SidebarMoreParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_sidebar_more = False
        self.sidebar_more_depth = 0
        self.anchor_depth = 0
        self.nested_buttons: list[dict[str, str]] = []
        self.rows: list[dict[str, str]] = []
        self._current_row: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "div" and attr.get("id") == "sidebarMoreContent":
            self.in_sidebar_more = True
            self.sidebar_more_depth = 1
            return

        if not self.in_sidebar_more:
            return

        if tag == "div":
            self.sidebar_more_depth += 1
            if attr.get("data-sidebar-href"):
                self._current_row = {
                    "href": attr["data-sidebar-href"],
                    "button_label": "",
                    "link_href": "",
                    "link_text": "",
                }
                self.rows.append(self._current_row)
        elif tag == "a":
            self.anchor_depth += 1
            if self._current_row is not None:
                self._current_row["link_href"] = attr.get("href", "")
        elif tag == "button":
            if self.anchor_depth:
                self.nested_buttons.append(attr)
            if self._current_row is not None:
                self._current_row["button_label"] = attr.get("aria-label", "")

    def handle_data(self, data: str) -> None:
        if self.in_sidebar_more and self.anchor_depth and self._current_row is not None:
            text = " ".join(data.split())
            if text:
                self._current_row["link_text"] = " ".join(
                    [self._current_row["link_text"], text]
                ).strip()

    def handle_endtag(self, tag: str) -> None:
        if not self.in_sidebar_more:
            return
        if tag == "a" and self.anchor_depth:
            self.anchor_depth -= 1
        elif tag == "div":
            self.sidebar_more_depth -= 1
            if self.sidebar_more_depth <= 0:
                self.in_sidebar_more = False
                self._current_row = None


def _assert_sidebar_more_controls_are_independent(app_name: str) -> None:
    base = (ROOT / app_name / "templates" / "base.html").read_text(encoding="utf-8")
    parser = _SidebarMoreParser()
    parser.feed(base)

    assert not parser.nested_buttons, f"{app_name}: sidebar more buttons must not be nested in links"
    assert len(parser.rows) >= 10, f"{app_name}: sidebar more rows were not parsed"
    for row in parser.rows:
        assert row["href"] == row["link_href"], f"{app_name}: row/link href mismatch: {row}"
        assert row["link_text"], f"{app_name}: sidebar more link needs visible text: {row}"
        assert row["button_label"].endswith("즐겨찾기 토글"), (
            f"{app_name}: favorite button needs a specific accessible name: {row}"
        )


@pytest.mark.asyncio
async def test_jm_dashboard_keyboard_focus_order_is_logical(jm: httpx.AsyncClient):
    response = await jm.get("/")

    assert response.status_code == 200
    _assert_dashboard_focus_order("jm", response.text)
    _assert_sidebar_keyboard_script_contract("jm")
    _assert_sidebar_more_controls_are_independent("jm")


@pytest.mark.asyncio
async def test_my_dashboard_keyboard_focus_order_is_logical(my: httpx.AsyncClient):
    await _setup_my_profile(my)
    response = await my.get("/")

    assert response.status_code == 200
    _assert_dashboard_focus_order("my", response.text)
    _assert_sidebar_keyboard_script_contract("my")
    _assert_sidebar_more_controls_are_independent("my")
