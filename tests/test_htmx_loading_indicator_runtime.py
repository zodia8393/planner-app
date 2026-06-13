import socket
import subprocess
import sys
import threading
import time
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:
    PlaywrightError = None
    sync_playwright = None


ROOT = Path(__file__).resolve().parents[1]


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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _asset_text(app_name: str, relative_path: str) -> str:
    return (ROOT / app_name / relative_path).read_text(encoding="utf-8")


def _css_declarations(css: str, selector: str) -> dict[str, str]:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.DOTALL)
    assert match is not None, selector

    declarations = {}
    for raw_declaration in match.group("body").split(";"):
        if ":" not in raw_declaration:
            continue
        name, value = raw_declaration.split(":", 1)
        declarations[name.strip()] = value.strip()
    return declarations


def _indicator_markup(indicator_id: str, indicator_class: str, label: str, text: str) -> str:
    return f"""
<div id="{indicator_id}" class="{indicator_class} htmx-indicator rounded-lg border px-3 py-2 text-sm font-medium"
 role="status" aria-live="polite" aria-atomic="true" aria-label="{label}">
 <span class="inline-flex items-center gap-2">
  <span class="inline-block h-2 w-2 rounded-full"></span>
  {text}
 </span>
</div>
"""


def _page_html(app_name: str, case: dict[str, str]) -> str:
    css = "\n".join(
        [
            _asset_text(app_name, "static/tailwind.css"),
            _asset_text(app_name, "static/css/app.css"),
        ]
    )
    htmx = _asset_text(app_name, "static/htmx.min.js")
    indicator = _indicator_markup(
        case["indicator_id"],
        case["indicator_class"],
        case["label"],
        case["text"],
    )

    if case["method"] == "get":
        trigger = f"""
<div id="todoPage" hx-indicator="#{case['indicator_id']}">
 <button id="trigger" hx-get="/slow" hx-target="#result" type="button">불러오기</button>
 {indicator}
 <div id="result"></div>
</div>
"""
    else:
        trigger = f"""
<form id="triggerForm" hx-{case['method']}="/slow" hx-indicator="#{case['indicator_id']}" hx-swap="none">
 <input name="title" value="runtime loading check">
 <button id="trigger" type="submit" aria-describedby="{case['indicator_id']}">저장</button>
 {indicator}
</form>
"""

    return f"""<!doctype html>
<html lang="ko">
<head>
 <meta charset="utf-8">
 <style>{css}</style>
</head>
<body>
 {trigger}
 <script>{htmx}</script>
</body>
</html>"""


def _initial_data_page_html(app_name: str) -> str:
    css = "\n".join(
        [
            _asset_text(app_name, "static/tailwind.css"),
            _asset_text(app_name, "static/css/app.css"),
        ]
    )
    htmx = _asset_text(app_name, "static/htmx.min.js")
    indicator = _indicator_markup(
        "todo-list-loading",
        "todo-list-loading",
        "할일 목록 불러오는 중",
        "할일 목록을 불러오는 중입니다",
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
 <meta charset="utf-8">
 <style>{css}</style>
</head>
<body>
 <main id="todoPage" hx-indicator="#todo-list-loading">
  <section aria-label="할일 목록" aria-describedby="todo-list-status">
   <div id="todo-list-status" class="sr-only" role="status" aria-live="polite" aria-atomic="true">
    할일 목록 상태: 로딩 중입니다.
   </div>
   {indicator}
   <div id="todoList" hx-get="/initial-list" hx-trigger="load" hx-swap="innerHTML" aria-busy="true">
    <div id="todo-initial-placeholder" role="status" aria-live="polite" aria-atomic="true">
     할일 목록을 준비하는 중입니다
    </div>
   </div>
  </section>
 </main>
 <script>{htmx}</script>
 <script>
  document.body.addEventListener('htmx:afterSwap', function (event) {{
   if (event.target && event.target.id === 'todoList') {{
    event.target.setAttribute('aria-busy', 'false');
    document.getElementById('todo-list-status').textContent = '할일 목록 상태: 1개 항목이 있습니다.';
   }}
  }});
 </script>
</body>
</html>"""


def _layout_loading_page_html(app_name: str, surface: str) -> str:
    css_chunks = [
        _asset_text(app_name, "static/tailwind.css"),
        _asset_text(app_name, "static/css/app.css"),
    ]
    if surface == "dashboard":
        css_chunks.append(_asset_text(app_name, "static/css/dashboard-grid.css"))
    css = "\n".join(css_chunks)
    htmx = _asset_text(app_name, "static/htmx.min.js")

    if surface == "dashboard":
        body = """
<body hx-indicator="#globalLoader">
 <div class="htmx-indicator" id="globalLoader"></div>
 <main id="mainContent" role="main" class="mx-auto w-full max-w-5xl px-4 py-4">
  <section class="dashboard-quick-actions mb-4" aria-label="빠른 작업">
   <a href="/todos#new" class="quick-command-card">
    <span class="quick-command-icon">+</span>
    <span>
     <span class="quick-command-title">할일 추가</span>
     <span class="quick-command-desc">자연어 날짜 인식</span>
    </span>
   </a>
   <button id="trigger" type="button" hx-get="/slow" hx-target="#dashboardGrid" hx-swap="none" class="quick-command-card">
    <span class="quick-command-icon">↻</span>
    <span>
     <span class="quick-command-title">대시보드 새로고침</span>
     <span class="quick-command-desc">로딩 중 안정성 확인</span>
    </span>
   </button>
  </section>
  <div id="dashboardGrid">
   <section class="dashboard-widget" data-widget="widget-row">
    <div class="widget-body">
     <div class="grid grid-cols-2 lg:grid-cols-4 gap-2 lg:gap-2">
      <article class="work-card rounded-xl p-4"><h2 class="text-sm font-bold">오늘 위젯</h2><p class="text-xs">할일 3 / 일정 2</p></article>
      <article class="work-card rounded-xl p-4"><h2 class="text-sm font-bold">주간 완료율</h2><p class="text-xs">2/5 완료</p></article>
      <article class="work-card rounded-xl p-4"><h2 class="text-sm font-bold">지연 업무</h2><p class="text-xs">지연 없음</p></article>
      <article class="work-card rounded-xl p-4"><h2 class="text-sm font-bold">오늘 진행</h2><p class="text-xs">40%</p></article>
     </div>
    </div>
   </section>
   <section class="dashboard-widget" data-widget="quick-add">
    <div class="widget-body">
     <div class="work-card rounded-xl overflow-hidden">
      <form class="px-3 py-2"><div class="flex gap-2"><input aria-label="빠른 업무 추가" class="flex-1 px-3.5 py-2.5 text-sm rounded-xl input-premium" value="긴 로딩 중에도 폭이 유지되는 빠른 추가 입력"><button type="button" class="px-5 py-2.5 text-sm font-semibold rounded-xl btn-accent">추가</button></div></form>
     </div>
    </div>
   </section>
  </div>
 </main>
 <script>"""
    else:
        indicator = _indicator_markup(
            "todo-list-loading",
            "todo-list-loading",
            "할일 목록 불러오는 중",
            "할일 목록을 불러오는 중입니다",
        )
        body = f"""
<body>
 <main id="mainContent" role="main" class="mx-auto w-full max-w-5xl px-4 py-4">
  <div id="todoPage" hx-indicator="#todo-list-loading">
   <div class="flex flex-wrap items-center gap-2 mb-3 overflow-x-auto scroll-fade-right pb-1">
    <a href="/todos" class="btn-sm rounded-lg font-semibold transition-colors whitespace-nowrap btn-primary shadow-sm">목록 보기</a>
    <a href="/todos?filter=active" class="btn-sm rounded-lg font-semibold transition-colors whitespace-nowrap border">미완료</a>
    <button id="trigger" type="button" hx-get="/slow" hx-target="#todoList" hx-swap="none" class="btn-sm rounded-lg font-semibold transition-colors whitespace-nowrap border">목록 새로고침</button>
   </div>
   <section aria-label="할일 목록">
    {indicator}
    <div id="todoList" role="list" class="space-y-2">
     <article class="work-card rounded-xl fade-in group touch-item swipe-item" role="listitem">
      <div class="swipe-content p-4">
       <div class="flex items-start gap-3">
        <div class="flex-1 min-w-0">
         <h2 class="font-semibold">로딩 중에도 카드 폭이 유지되는 할일</h2>
         <p class="text-sm" style="color: var(--color-text-muted);">주요 목록 레이아웃이 모바일과 데스크톱에서 가로로 넘치지 않아야 합니다.</p>
        </div>
        <button type="button" class="btn-sm rounded-lg border">수정</button>
       </div>
      </div>
     </article>
    </div>
   </section>
  </div>
 </main>
 <script>"""

    return f"""<!doctype html>
<html lang="ko">
<head>
 <meta charset="utf-8">
 <style>{css}</style>
</head>
{body}{htmx}</script>
</body>
</html>"""


class _DelayedHtmxHandler(BaseHTTPRequestHandler):
    html = ""
    delay_seconds = 0.35
    create_response = ""
    edit_response = ""

    def log_message(self, format, *args):  # noqa: A002
        return

    def do_GET(self):
        if self.path == "/":
            self._send(200, self.html, "text/html; charset=utf-8")
            return
        if self.path == "/slow":
            time.sleep(self.delay_seconds)
            self._send(200, "<div id='result'>완료</div>", "text/html; charset=utf-8")
            return
        if self.path == "/initial-list":
            time.sleep(self.delay_seconds)
            self._send(
                200,
                """
                <article id="todo-loaded-item" role="listitem">
                 <h2>초기 로딩 완료 항목</h2>
                 <p>지연 응답 후 표시되는 목록 콘텐츠입니다.</p>
                </article>
                """,
                "text/html; charset=utf-8",
            )
            return
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path == "/todos" and self.create_response:
            time.sleep(self.delay_seconds)
            self._send(200, self.create_response, "text/html; charset=utf-8")
            return
        self._delayed_empty_response()

    def do_PUT(self):
        if self.path == "/todos/42" and self.edit_response:
            time.sleep(self.delay_seconds)
            self._send(200, self.edit_response, "text/html; charset=utf-8")
            return
        self._delayed_empty_response()

    def _delayed_empty_response(self):
        time.sleep(self.delay_seconds)
        self._send(204, "", "text/plain")

    def _send(self, status: int, body: str, content_type: str):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _serve_html(html: str):
    handler = type("DelayedHtmxHandler", (_DelayedHtmxHandler,), {"html": html})
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def _serve_focus_html(html: str, create_response: str, edit_response: str):
    handler = type(
        "FocusHtmxHandler",
        (_DelayedHtmxHandler,),
        {
            "html": html,
            "create_response": create_response,
            "edit_response": edit_response,
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def _focus_flow_page_html(app_name: str) -> str:
    css = "\n".join(
        [
            _asset_text(app_name, "static/tailwind.css"),
            _asset_text(app_name, "static/css/app.css"),
        ]
    )
    htmx = _asset_text(app_name, "static/htmx.min.js")
    actions_js = _asset_text(app_name, "static/js/actions.js")
    return f"""<!doctype html>
<html lang="ko">
<head>
 <meta charset="utf-8">
 <style>{css}</style>
</head>
<body>
 <main id="mainContent" role="main">
  <section id="todoCreateShell" aria-label="할일 생성">
   {_create_focus_response()}
  </section>
  <section aria-label="할일 수정">
   <article id="todo-42" class="work-card rounded-xl">
    <form id="editTodoForm-42" hx-put="/todos/42" hx-target="#todo-42" hx-swap="outerHTML" hx-indicator="#todo-edit-loading-42">
     <input id="todo-edit-title-42" name="title" value="수정 전 항목" required aria-label="할일 제목">
     <div id="todo-edit-loading-42" class="todo-edit-loading htmx-indicator" role="status" aria-live="polite" aria-atomic="true" aria-label="할일 저장 중" tabindex="0">
      변경사항을 저장하는 중입니다
     </div>
     <button id="editSubmit" type="submit" aria-describedby="todo-edit-loading-42">저장</button>
    </form>
   </article>
  </section>
 </main>
 <script>{htmx}</script>
 <script>{actions_js}</script>
</body>
</html>"""


def _create_focus_response(feedback: str = "") -> str:
    feedback_html = ""
    if feedback:
        feedback_html = f"""
   <div id="todo-create-feedback" role="status" aria-live="polite" aria-atomic="true" aria-label="할일 추가 성공">
    {feedback}
   </div>
"""
    return f"""
   {feedback_html}
   <form id="addTodoForm" hx-post="/todos" hx-target="#todoCreateShell" hx-swap="innerHTML" hx-indicator="#todo-create-loading">
    <input id="newTodoTitle" name="title" required aria-label="새 업무 제목" aria-describedby="todo-create-loading">
    <div id="todo-create-loading" class="todo-create-loading htmx-indicator" role="status" aria-live="polite" aria-atomic="true" aria-label="할일 추가 중">
     할일을 추가하는 중입니다
    </div>
    <button id="createSubmit" type="submit" aria-describedby="todo-create-loading">추가</button>
   </form>
"""


def _edit_focus_response() -> str:
    return """
   <article id="todo-42" class="work-card rounded-xl">
    <div id="todo-edit-success-42" class="todo-edit-success focus-accent" role="status" aria-live="polite" aria-atomic="true" aria-label="할일 저장 성공" tabindex="0" data-todo-save-feedback>
     변경사항이 저장되었습니다.
    </div>
    <p>수정 후 항목</p>
   </article>
"""


def _indicator_state(page, indicator_id: str) -> dict:
    return page.locator(f"#{indicator_id}").evaluate(
        """(el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return {
                className: el.className,
                display: style.display,
                opacity: style.opacity,
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                text: el.textContent.replace(/\\s+/g, ' ').trim(),
            };
        }"""
    )


def _layout_metrics(page, surface: str) -> dict:
    target_selector = "#dashboardGrid" if surface == "dashboard" else "#todoList"
    return page.evaluate(
        """(targetSelector) => {
            const viewportWidth = window.innerWidth;
            const rectFor = (selector) => {
                const el = document.querySelector(selector);
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    top: Math.round(rect.top),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    hasHorizontalScroll: el.scrollWidth > el.clientWidth + 2,
                };
            };
            return {
                viewportWidth,
                documentScrollWidth: document.documentElement.scrollWidth,
                bodyScrollWidth: document.body.scrollWidth,
                main: rectFor('#mainContent'),
                target: rectFor(targetSelector),
                indicator: rectFor('#globalLoader') || rectFor('#todo-list-loading'),
            };
        }""",
        target_selector,
    )


def _assert_loading_layout_stable(before: dict, during: dict, after: dict, surface: str):
    for state_name, metrics in (("before", before), ("during", during), ("after", after)):
        viewport_width = metrics["viewportWidth"]
        assert metrics["documentScrollWidth"] <= viewport_width + 1, (surface, state_name, metrics)
        assert metrics["bodyScrollWidth"] <= viewport_width + 1, (surface, state_name, metrics)
        for key in ("main", "target"):
            rect = metrics[key]
            assert rect is not None, (surface, state_name, key, metrics)
            assert rect["width"] > 0, (surface, state_name, key, metrics)
            assert rect["right"] <= viewport_width + 1, (surface, state_name, key, metrics)
            assert rect["left"] >= -1, (surface, state_name, key, metrics)
            assert not rect["hasHorizontalScroll"], (surface, state_name, key, metrics)

    for key in ("main", "target"):
        assert abs(during[key]["width"] - before[key]["width"]) <= 1, (surface, key, before, during)
        assert abs(after[key]["width"] - before[key]["width"]) <= 1, (surface, key, before, after)


CASES = [
    {
        "name": "list",
        "method": "get",
        "indicator_id": "todo-list-loading",
        "indicator_class": "todo-list-loading",
        "label": "할일 목록 불러오는 중",
        "text": "할일 목록을 불러오는 중입니다",
    },
    {
        "name": "create",
        "method": "post",
        "indicator_id": "todo-create-loading",
        "indicator_class": "todo-create-loading",
        "label": "할일 추가 중",
        "text": "할일을 추가하는 중입니다",
    },
    {
        "name": "edit",
        "method": "put",
        "indicator_id": "todo-edit-loading-42",
        "indicator_class": "todo-edit-loading",
        "label": "할일 저장 중",
        "text": "변경사항을 저장하는 중입니다",
    },
]


@pytest.mark.parametrize("app_name", ["jm", "my"])
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_core_todo_loading_indicator_request_lifecycle_contract_is_executable(
    app_name: str,
    case: dict[str, str],
):
    css = _asset_text(app_name, "static/css/app.css")
    selector = f".{case['indicator_class']}.htmx-indicator"
    request_selector = f"{selector}.htmx-request"
    after_selector = f"{request_selector}::after"
    markup = _indicator_markup(
        case["indicator_id"],
        case["indicator_class"],
        case["label"],
        case["text"],
    )

    initial_style = _css_declarations(css, selector)
    request_style = {**initial_style, **_css_declarations(css, request_selector)}
    completed_style = initial_style
    after_style = _css_declarations(css, after_selector)

    assert f'id="{case["indicator_id"]}"' in markup
    assert f'aria-label="{case["label"]}"' in markup
    assert 'role="status"' in markup
    assert 'aria-live="polite"' in markup
    assert case["text"] in markup

    assert initial_style["display"] == "none"
    assert initial_style["opacity"] == "0"
    assert request_style["display"] == "block"
    assert request_style["opacity"] == "1"
    assert after_style["display"] == "none"
    assert completed_style["display"] == "none"
    assert completed_style["opacity"] == "0"


@pytest.mark.parametrize("app_name", ["jm", "my"])
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_core_todo_htmx_loading_indicator_toggles_during_request(
    optional_chromium_browser,
    app_name: str,
    case: dict[str, str],
):
    if optional_chromium_browser is None:
        pytest.skip("Playwright Chromium is not available")

    server, url = _serve_html(_page_html(app_name, case))
    context = optional_chromium_browser.new_context(java_script_enabled=True)
    page = context.new_page()

    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("() => window.htmx !== undefined")

        initial = _indicator_state(page, case["indicator_id"])
        assert initial["display"] == "none"
        assert initial["text"] == case["text"]

        page.locator("#trigger").click(no_wait_after=True)
        page.wait_for_function(
            """(indicatorId) => {
                const el = document.getElementById(indicatorId);
                return el && el.classList.contains('htmx-request');
            }""",
            arg=case["indicator_id"],
            timeout=1000,
        )
        during = _indicator_state(page, case["indicator_id"])
        assert during["display"] != "none"
        assert during["opacity"] == "1"
        assert during["height"] > 0

        page.wait_for_function(
            """(indicatorId) => {
                const el = document.getElementById(indicatorId);
                return el && !el.classList.contains('htmx-request');
            }""",
            arg=case["indicator_id"],
            timeout=3000,
        )
        completed = _indicator_state(page, case["indicator_id"])
        assert completed["display"] == "none"
    finally:
        context.close()
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("app_name", ["jm", "my"])
def test_core_todo_initial_data_loading_transitions_from_loading_to_content(
    optional_chromium_browser,
    app_name: str,
):
    if optional_chromium_browser is None:
        pytest.skip("Playwright Chromium is not available")

    server, url = _serve_html(_initial_data_page_html(app_name))
    context = optional_chromium_browser.new_context(java_script_enabled=True)
    page = context.new_page()

    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("() => window.htmx !== undefined")

        placeholder = page.locator("#todo-initial-placeholder")
        assert placeholder.is_visible()
        assert "할일 목록을 준비하는 중입니다" in placeholder.inner_text()
        assert page.locator("#todoList").get_attribute("aria-busy") == "true"

        page.wait_for_function(
            """() => {
                const el = document.getElementById('todo-list-loading');
                return el && el.classList.contains('htmx-request');
            }""",
            timeout=1000,
        )
        during = _indicator_state(page, "todo-list-loading")
        assert during["display"] != "none"
        assert during["opacity"] == "1"
        assert during["text"] == "할일 목록을 불러오는 중입니다"

        page.wait_for_selector("#todo-loaded-item", state="visible", timeout=3000)
        assert page.locator("#todo-loaded-item").inner_text().count("초기 로딩 완료 항목") == 1
        assert page.locator("#todo-initial-placeholder").count() == 0
        assert page.locator("#todoList").get_attribute("aria-busy") == "false"
        assert "1개 항목" in page.locator("#todo-list-status").inner_text()

        completed = _indicator_state(page, "todo-list-loading")
        assert completed["display"] == "none"
    finally:
        context.close()
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("app_name", ["jm", "my"])
def test_core_todo_create_and_edit_htmx_updates_keep_expected_focus(
    optional_chromium_browser,
    app_name: str,
):
    if optional_chromium_browser is None:
        pytest.skip("Playwright Chromium is not available")

    server, url = _serve_focus_html(
        _focus_flow_page_html(app_name),
        _create_focus_response("할일이 추가되었습니다."),
        _edit_focus_response(),
    )
    context = optional_chromium_browser.new_context(java_script_enabled=True)
    page = context.new_page()

    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("() => window.htmx !== undefined")

        title = page.locator("#newTodoTitle")
        title.fill(f"{app_name} focus create")
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "newTodoTitle"

        title.press("Enter")
        page.wait_for_selector("#todo-create-feedback", state="visible", timeout=3000)
        page.wait_for_function(
            "() => document.activeElement && document.activeElement.id === 'newTodoTitle'",
            timeout=1000,
        )
        assert page.locator("#todo-create-feedback").inner_text().strip() == "할일이 추가되었습니다."

        page.locator("#todo-edit-title-42").fill(f"{app_name} focus edit")
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "todo-edit-title-42"

        page.locator("#editSubmit").click(no_wait_after=True)
        page.wait_for_selector("#todo-edit-success-42", state="visible", timeout=3000)
        page.wait_for_function(
            "() => document.activeElement && document.activeElement.id === 'todo-edit-success-42'",
            timeout=1000,
        )
        focused = page.locator("#todo-edit-success-42")
        assert focused.get_attribute("role") == "status"
        assert focused.get_attribute("aria-live") == "polite"
        assert focused.get_attribute("data-todo-save-feedback") == ""
    finally:
        context.close()
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("app_name", ["jm", "my"])
@pytest.mark.parametrize("surface", ["dashboard", "list"])
@pytest.mark.parametrize(
    "viewport",
    [{"width": 1440, "height": 900}, {"width": 390, "height": 844}],
    ids=["desktop_1440x900", "mobile_390x844"],
)
def test_main_dashboard_and_list_loading_states_keep_layout_stable(
    optional_chromium_browser,
    app_name: str,
    surface: str,
    viewport: dict[str, int],
):
    if optional_chromium_browser is None:
        pytest.skip("Playwright Chromium is not available")

    server, url = _serve_html(_layout_loading_page_html(app_name, surface))
    context = optional_chromium_browser.new_context(
        java_script_enabled=True,
        viewport=viewport,
    )
    page = context.new_page()
    indicator_id = "globalLoader" if surface == "dashboard" else "todo-list-loading"

    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("() => window.htmx !== undefined")

        before = _layout_metrics(page, surface)
        page.locator("#trigger").click(no_wait_after=True)
        page.wait_for_function(
            """(indicatorId) => {
                const el = document.getElementById(indicatorId);
                return el && el.classList.contains('htmx-request');
            }""",
            arg=indicator_id,
            timeout=1000,
        )
        during = _layout_metrics(page, surface)
        assert during["indicator"]["width"] <= viewport["width"] + 1
        assert during["indicator"]["height"] > 0

        page.wait_for_function(
            """(indicatorId) => {
                const el = document.getElementById(indicatorId);
                return el && !el.classList.contains('htmx-request');
            }""",
            arg=indicator_id,
            timeout=3000,
        )
        after = _layout_metrics(page, surface)

        _assert_loading_layout_stable(before, during, after, surface)
    finally:
        context.close()
        server.shutdown()
        server.server_close()
