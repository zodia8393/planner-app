"""
Screenshot-backed readability and contrast checks for the jm/my MVP core todo list.

The selected first-entry core list for both planner instances is /todos. App
fixtures use isolated temporary databases, so the visible todo created here
does not touch production data.
"""

import re
import struct
import subprocess
import sys
import zlib
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
ORIGIN = {"origin": "http://testserver", "host": "testserver"}
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}
BASELINE_SCREENSHOTS = {
    "desktop": ROOT / "screenshots_mobile" / "pc_todos.png",
    "mobile": ROOT / "screenshots_mobile" / "mobile_todos.png",
}


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


def _insert_visible_todo(mod, profile_id: int, app_name: str) -> int:
    title = f"{app_name} core todo visual contrast {uuid4().hex[:10]}"
    with mod.get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM todos WHERE profile_id=?",
            (profile_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO todos (
                profile_id, title, description, priority, due_date, tags,
                energy_level, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                title,
                "Visual regression item with readable metadata and status text.",
                1,
                "2026-06-12",
                '["mvp-visual-contrast"]',
                3,
                max_order + 1,
            ),
        )
        todo_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO subtasks (todo_id, title, sort_order) VALUES (?, ?, ?)",
            (todo_id, "Verify rendered contrast", 1),
        )
        return todo_id


async def _fetch_core_todo_html(app_name: str, app, mod) -> tuple[str, int]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"CoreTodoVisual{uuid4().hex[:8]}"
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

        todo_id = _insert_visible_todo(mod, profile_id, app_name)
        response = await client.get("/todos")
        assert response.status_code == 200, f"{app_name} /todos: status {response.status_code}"
        assert f'id="todo-{todo_id}"' in response.text
        return response.text, todo_id


async def _fetch_core_todo_edit_html(app_name: str, app, mod) -> tuple[str, int]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"CoreTodoEditVisual{uuid4().hex[:8]}"
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

        title = f"{app_name} editable field contrast {uuid4().hex[:10]}"
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
                    "Editable field visual regression item.",
                    2,
                    "2026-06-12",
                    "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=6",
                    '["mvp-edit-visual"]',
                    2,
                    max_order + 1,
                ),
            )
            todo_id = int(cur.lastrowid)

        response = await client.get(
            f"/todos/{todo_id}/edit",
            headers={**ORIGIN, "HX-Request": "true"},
        )
        assert response.status_code == 200, f"{app_name} edit form: status {response.status_code}"
        assert f'id="editTodoForm-{todo_id}"' in response.text
        return response.text, todo_id


def _app_asset(app_name: str, relative_path: str) -> str:
    return (ROOT / app_name / relative_path).read_text(encoding="utf-8")


def _inline_render_css(app_name: str, html: str) -> str:
    css_chunks = [
        _app_asset(app_name, "static/tailwind.css"),
        _app_asset(app_name, "static/css/app.css"),
    ]
    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r'<script\b[^>]*\bsrc="[^"]+"[^>]*></script>', "", html)
    test_css = """
        *, *::before, *::after {
            animation: none !important;
            transition: none !important;
            caret-color: transparent !important;
        }
    """
    return html.replace("</head>", f"<style>{' '.join(css_chunks)} {test_css}</style></head>")


def _inline_edit_render_css(app_name: str, edit_html: str) -> str:
    css_chunks = [
        _app_asset(app_name, "static/tailwind.css"),
        _app_asset(app_name, "static/css/app.css"),
    ]
    test_css = """
        *, *::before, *::after {
            animation: none !important;
            transition: none !important;
            caret-color: transparent !important;
        }
    """
    return f"""
    <html>
      <head><style>{' '.join(css_chunks)} {test_css}</style></head>
      <body style="background: var(--color-bg); color: var(--color-text);">
        <main id="mainContent">
          <section id="todoPage" class="p-4">{edit_html}</section>
        </main>
      </body>
    </html>
    """


def _editable_field_boxes(page):
    return page.evaluate(
        """() => Array.from(document.querySelectorAll(
            '#todoPage [id^="editTodoForm-"] input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), ' +
            '#todoPage [id^="editTodoForm-"] select, ' +
            '#todoPage [id^="editTodoForm-"] textarea'
        ))
            .filter((el) => el instanceof HTMLElement)
            .filter((el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    Number.parseFloat(style.opacity || '1') > 0.01 &&
                    rect.width >= 8 &&
                    rect.height >= 8;
            })
            .map((el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                const name = el.getAttribute('aria-label') ||
                    el.getAttribute('name') ||
                    el.id ||
                    el.tagName.toLowerCase();
                return {
                    name,
                    tag: el.tagName.toLowerCase(),
                    color: style.color,
                    backgroundColor: style.backgroundColor,
                    borderColor: style.borderColor,
                    fontSize: Number.parseFloat(style.fontSize) || 16,
                    rect: {
                        left: Math.max(0, Math.floor(rect.left)),
                        top: Math.max(0, Math.floor(rect.top)),
                        right: Math.min(window.innerWidth, Math.ceil(rect.right)),
                        bottom: Math.min(window.innerHeight, Math.ceil(rect.bottom)),
                    },
                };
            })"""
    )


def _readability_boxes(page):
    return page.evaluate(
        """() => {
            const directText = (el) => Array.from(el.childNodes)
                .filter((node) => node.nodeType === Node.TEXT_NODE)
                .map((node) => node.textContent.trim())
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();
            const readableName = (el) => {
                if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                    return el.value || el.placeholder || el.getAttribute('aria-label') || '';
                }
                if (el instanceof HTMLSelectElement) {
                    return el.getAttribute('aria-label') || el.options[el.selectedIndex]?.text || '';
                }
                return directText(el) || el.getAttribute('aria-label') || '';
            };
            const solidBackground = (el) => {
                let current = el;
                while (current && current instanceof HTMLElement) {
                    const bg = getComputedStyle(current).backgroundColor;
                    const match = bg.match(/rgba?\\(([^)]+)\\)/);
                    if (match) {
                        const parts = match[1].split(',').map((part) => Number.parseFloat(part.trim()));
                        if (parts.length < 4 || parts[3] > 0.02) return bg;
                    }
                    current = current.parentElement;
                }
                return getComputedStyle(document.body).backgroundColor;
            };
            const selectors = [
                '.common-app-header h2',
                '.common-app-header p',
                '.common-app-header .date-badge',
                '#todoPage summary',
                '#todoPage a',
                '#todoPage button',
                '#todoPage input',
                '#todoPage select',
                '#todoPage label',
                '#todoPage h1',
                '#todoPage h2',
                '#todoPage h3',
                '#todoPage p',
                '#todoPage article span',
                '#todoPage article a',
                '#todoPage .text-xs',
                '#todoPage .text-sm',
                '#todoPage .font-medium',
                '#todoPage .font-semibold'
            ].join(',');
            return Array.from(document.querySelectorAll(selectors))
                .filter((el) => el instanceof HTMLElement)
                .filter((el) => {
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    if (Number.parseFloat(style.opacity || '1') <= 0.01) return false;
                    if (!readableName(el)) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width >= 4 &&
                        rect.height >= 4 &&
                        rect.right > 0 &&
                        rect.bottom > 0 &&
                        rect.left < window.innerWidth &&
                        rect.top < window.innerHeight;
                })
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return {
                        text: readableName(el).slice(0, 90),
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 140),
                        color: style.color,
                        backgroundColor: solidBackground(el),
                        fontSize: Number.parseFloat(style.fontSize) || 16,
                        fontWeight: style.fontWeight,
                        rect: {
                            left: Math.max(0, Math.floor(rect.left)),
                            top: Math.max(0, Math.floor(rect.top)),
                            right: Math.min(window.innerWidth, Math.ceil(rect.right)),
                            bottom: Math.min(window.innerHeight, Math.ceil(rect.bottom)),
                        },
                    };
                });
        }"""
    )


def _png_rgba_pixels(png_bytes: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n"), "screenshot is not a PNG"
    offset = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    while offset < len(png_bytes):
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        chunk_data = png_bytes[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    assert width and height and bit_depth == 8 and color_type in (2, 6), (
        f"unsupported screenshot PNG format: {width=} {height=} {bit_depth=} {color_type=}"
    )
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = zlib.decompress(bytes(idat))
    rows: list[bytearray] = []
    cursor = 0
    previous = bytearray(stride)
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        for index in range(stride):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + up) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                predictor = left + up - up_left
                pa = abs(predictor - left)
                pb = abs(predictor - up)
                pc = abs(predictor - up_left)
                prior = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
                row[index] = (row[index] + prior) & 0xFF
            elif filter_type != 0:
                raise AssertionError(f"unsupported PNG filter: {filter_type}")
        rows.append(row)
        previous = row

    pixels: list[tuple[int, int, int, int]] = []
    for row in rows:
        for index in range(0, stride, channels):
            alpha = row[index + 3] if channels == 4 else 255
            pixels.append((row[index], row[index + 1], row[index + 2], alpha))
    return width, height, pixels


def _rgb(css_color: str) -> tuple[int, int, int]:
    match = re.match(r"rgba?\(([^)]+)\)", css_color)
    assert match, f"unsupported CSS color: {css_color}"
    red, green, blue, *_ = [int(float(part.strip())) for part in match.group(1).split(",")]
    return red, green, blue


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        if normalized <= 0.03928:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    red, green, blue = rgb
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def _contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    lighter = max(_luminance(a), _luminance(b))
    darker = min(_luminance(a), _luminance(b))
    return (lighter + 0.05) / (darker + 0.05)


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    assert re.fullmatch(r"[0-9a-fA-F]{6}", value), f"unsupported hex color: {value}"
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _root_color_tokens(app_name: str) -> dict[str, str]:
    css = _app_asset(app_name, "static/css/app.css")
    root_match = re.search(r":root\s*\{(?P<body>.*?)\n\s*\}", css, re.S)
    assert root_match, f"{app_name}: missing :root color tokens"
    return {
        name: value
        for name, value in re.findall(
            r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;",
            root_match.group("body"),
        )
    }


def _crop_luminance_span(width: int, pixels: list[tuple[int, int, int, int]], rect: dict) -> float:
    luminances: list[float] = []
    for y in range(rect["top"], rect["bottom"]):
        for x in range(rect["left"], rect["right"]):
            red, green, blue, alpha = pixels[(y * width) + x]
            if alpha:
                luminances.append(_luminance((red, green, blue)))
    assert luminances, f"empty screenshot crop for {rect}"
    luminances.sort()
    low = luminances[max(0, int(len(luminances) * 0.01) - 1)]
    high = luminances[min(len(luminances) - 1, int(len(luminances) * 0.99))]
    return round(high - low, 3)


@pytest.mark.parametrize("screenshot_name,screenshot_path", BASELINE_SCREENSHOTS.items())
def test_core_todo_visual_baseline_screenshot_preserves_readable_contrast(
    screenshot_name, screenshot_path
):
    assert screenshot_path.exists(), f"missing /todos visual baseline: {screenshot_path}"
    width, height, pixels = _png_rgba_pixels(screenshot_path.read_bytes())

    assert width >= 390, f"{screenshot_name}: /todos baseline width is too small"
    assert height >= 844, f"{screenshot_name}: /todos baseline height is too small"

    colors = [(red, green, blue) for red, green, blue, alpha in pixels if alpha]
    colors.sort(key=_luminance)
    darkest = colors[max(0, int(len(colors) * 0.001) - 1)]
    lightest = colors[min(len(colors) - 1, int(len(colors) * 0.97))]
    contrast = _contrast_ratio(darkest, lightest)
    luminance_span = _luminance(lightest) - _luminance(darkest)
    dark_pixel_count = sum(1 for color in colors if _luminance(color) < 0.25)

    assert contrast >= 4.5, (
        f"{screenshot_name}: /todos visual baseline contrast {contrast:.2f} < 4.5"
    )
    assert luminance_span >= 0.55, (
        f"{screenshot_name}: /todos visual baseline luminance span "
        f"{luminance_span:.2f} is too narrow"
    )
    assert dark_pixel_count >= 1000, (
        f"{screenshot_name}: /todos visual baseline has too few dark text pixels"
    )


@pytest.mark.parametrize("viewport_name,viewport", VIEWPORTS.items())
@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_screenshot_preserves_text_readability_and_contrast(
    optional_chromium_browser, viewport_name, viewport, app_name, app, mod
):
    html_response, todo_id = run_async(_fetch_core_todo_html(app_name, app, mod))
    assert "업무 관리" in html_response
    assert 'id="todoPage"' in html_response
    assert 'aria-label="할일 목록"' in html_response
    assert f'id="todo-{todo_id}"' in html_response

    if optional_chromium_browser is None:
        return

    context = optional_chromium_browser.new_context(
        viewport=viewport,
        java_script_enabled=False,
        device_scale_factor=1,
        is_mobile=viewport_name == "mobile",
        has_touch=viewport_name == "mobile",
    )
    page = context.new_page()
    page.set_content(_inline_render_css(app_name, html_response), wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    boxes = _readability_boxes(page)
    visible_text = " ".join(box["text"] for box in boxes)
    assert "새 업무 제목" in visible_text, (
        f"{app_name} {viewport_name}: creation form label is missing from visual render"
    )
    assert "제목을 입력한 뒤 추가를 누르세요." in visible_text, (
        f"{app_name} {viewport_name}: creation form help text is missing from visual render"
    )
    assert "할 일 입력" in visible_text, (
        f"{app_name} {viewport_name}: creation form placeholder is missing from visual render"
    )
    assert "추가" in visible_text, (
        f"{app_name} {viewport_name}: creation submit button text is missing from visual render"
    )
    screenshot = page.screenshot(type="png", full_page=False)
    width, height, pixels = _png_rgba_pixels(screenshot)

    assert width == viewport["width"], f"{app_name} {viewport_name}: wrong screenshot width"
    assert height == viewport["height"], f"{app_name} {viewport_name}: wrong screenshot height"
    assert len(boxes) >= (36 if viewport_name == "desktop" else 24), (
        f"{app_name} {viewport_name}: too few visible todo text boxes: {boxes}"
    )

    contrast_offenders = []
    visible_ink_boxes = 0
    for box in boxes:
        ratio = _contrast_ratio(_rgb(box["color"]), _rgb(box["backgroundColor"]))
        required_ratio = 3.0 if box["fontSize"] >= 18 else 4.5
        if ratio < required_ratio:
            contrast_offenders.append({**box, "contrast": round(ratio, 2)})
        if _crop_luminance_span(width, pixels, box["rect"]) >= 0.04:
            visible_ink_boxes += 1

    assert not contrast_offenders, (
        f"{app_name} {viewport_name}: /todos text contrast regressed: "
        f"{contrast_offenders[:12]}"
    )
    assert visible_ink_boxes >= (24 if viewport_name == "desktop" else 16), (
        f"{app_name} {viewport_name}: screenshot did not preserve enough readable "
        f"text luminance detail: {visible_ink_boxes=} {boxes[:12]}"
    )

    page.close()
    context.close()


@pytest.mark.parametrize("app_name", ["jm", "my"])
def test_jm_my_core_todo_edit_save_feedback_uses_accessible_status_contrast(app_name):
    app_css = _app_asset(app_name, "static/css/app.css")

    assert ".todo-edit-success {\n  background: var(--color-success-soft);" in app_css
    assert ".todo-edit-error {\n  background: var(--color-danger-soft);" in app_css
    assert ".todo-edit-loading.htmx-indicator {" in app_css
    assert "background: var(--color-info-soft);" in app_css

    tokens = _root_color_tokens(app_name)
    status_pairs = [
        ("--color-success", "--color-success-soft", "save success"),
        ("--color-danger", "--color-danger-soft", "save error"),
        ("--color-info", "--color-info-soft", "saving"),
    ]
    for foreground, background, label in status_pairs:
        ratio = _contrast_ratio(_hex_rgb(tokens[foreground]), _hex_rgb(tokens[background]))
        assert ratio >= 4.5, (
            f"{app_name}: todo edit {label} contrast {ratio:.2f} < 4.5"
        )


@pytest.mark.parametrize("viewport_name,viewport", VIEWPORTS.items())
@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_core_todo_edit_fields_preserve_accessible_visual_contrast(
    optional_chromium_browser, viewport_name, viewport, app_name, app, mod
):
    edit_html, todo_id = run_async(_fetch_core_todo_edit_html(app_name, app, mod))
    app_css = _app_asset(app_name, "static/css/app.css")

    contrast_selector = (
        '#todoPage :where([id^="editTodoForm-"] input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), '
        '[id^="editTodoForm-"] select, [id^="editTodoForm-"] textarea)'
    )
    assert contrast_selector in app_css
    assert "background: var(--color-surface);" in app_css
    assert "color: var(--color-text);" in app_css
    assert "border-color: var(--color-border);" in app_css
    assert f'id="editTodoForm-{todo_id}"' in edit_html
    assert 'aria-label="할일 제목"' in edit_html
    assert 'aria-label="설명"' in edit_html
    assert 'aria-label="마감일"' in edit_html
    assert 'aria-label="우선순위"' in edit_html
    assert 'aria-label="카테고리"' in edit_html
    assert 'aria-label="반복 설정"' in edit_html
    assert 'aria-label="에너지 레벨"' in edit_html
    assert 'aria-label="태그"' in edit_html

    if optional_chromium_browser is None:
        return

    context = optional_chromium_browser.new_context(
        viewport=viewport,
        java_script_enabled=False,
        device_scale_factor=1,
        is_mobile=viewport_name == "mobile",
        has_touch=viewport_name == "mobile",
    )
    page = context.new_page()
    page.set_content(_inline_edit_render_css(app_name, edit_html), wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    boxes = _editable_field_boxes(page)
    names = {box["name"] for box in boxes}
    assert {"할일 제목", "설명", "마감일", "우선순위", "카테고리", "반복 설정", "에너지 레벨", "태그"} <= names
    assert len(boxes) >= 12, f"{app_name} {viewport_name}: too few editable fields rendered: {boxes}"

    contrast_offenders = []
    border_offenders = []
    for box in boxes:
        ratio = _contrast_ratio(_rgb(box["color"]), _rgb(box["backgroundColor"]))
        if ratio < 4.5:
            contrast_offenders.append({**box, "contrast": round(ratio, 2)})
        border_ratio = _contrast_ratio(_rgb(box["borderColor"]), _rgb(box["backgroundColor"]))
        if border_ratio < 1.2:
            border_offenders.append({**box, "borderContrast": round(border_ratio, 2)})

    assert not contrast_offenders, (
        f"{app_name} {viewport_name}: edit field text contrast regressed: "
        f"{contrast_offenders[:12]}"
    )
    assert not border_offenders, (
        f"{app_name} {viewport_name}: edit field borders are too faint: "
        f"{border_offenders[:12]}"
    )

    page.close()
    context.close()
