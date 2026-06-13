"""
Screenshot-backed visual regression checks for jm/my dashboard readability.

The apps are imported through conftest.py with isolated temp databases. The
test captures the rendered dashboard in Chromium when available, then samples
major text boxes from the screenshot so low-contrast or invisible dashboard
text cannot regress silently.
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
    "desktop": ROOT / "screenshots_mobile" / "pc_dashboard.png",
    "mobile": ROOT / "screenshots_mobile" / "mobile_dashboard.png",
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


def _clear_dashboard_data(mod, profile_id: int) -> None:
    with mod.get_db() as conn:
        for table in ("todos", "events", "memos", "work_logs"):
            conn.execute(f"DELETE FROM {table} WHERE profile_id=?", (profile_id,))


async def _fetch_dashboard_html(app_name: str, app, mod) -> str:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        profile_id = 1
        if app_name == "my":
            profile_name = f"DashboardVisual{uuid4().hex[:8]}"
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

        _clear_dashboard_data(mod, profile_id)
        response = await client.get("/")
        assert response.status_code == 200, f"{app_name} /: status {response.status_code}"
        return response.text


def _app_css(app_name: str, relative_path: str) -> str:
    return (ROOT / app_name / relative_path).read_text(encoding="utf-8")


def _inline_render_css(app_name: str, html: str) -> str:
    css_chunks = [
        _app_css(app_name, "static/tailwind.css"),
        _app_css(app_name, "static/css/app.css"),
        _app_css(app_name, "static/css/dashboard-grid.css"),
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


def _visual_text_boxes(page):
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
            const textRect = (el) => {
                if (el instanceof HTMLInputElement ||
                    el instanceof HTMLTextAreaElement ||
                    el instanceof HTMLSelectElement) {
                    return null;
                }
                const node = Array.from(el.childNodes)
                    .find((child) => child.nodeType === Node.TEXT_NODE && child.textContent.trim());
                if (!node) return null;
                const range = document.createRange();
                range.selectNodeContents(node);
                const rect = range.getBoundingClientRect();
                range.detach();
                if (rect.width < 4 || rect.height < 4) return null;
                return rect;
            };
            const selectors = [
                '.common-app-header h2',
                '.common-app-header p',
                '.common-app-header .date-badge',
                '#mainContent summary',
                '#mainContent h1',
                '#mainContent h2',
                '#mainContent h3',
                '#mainContent p',
                '#mainContent label',
                '#mainContent button',
                '#mainContent input',
                '#mainContent textarea',
                '#mainContent select',
                '#mainContent .quick-command-title',
                '#mainContent .quick-command-desc',
                '#mainContent .empty-state-primary',
                '#dashboardGrid .text-xs',
                '#dashboardGrid .text-sm',
                '#dashboardGrid .font-bold',
                '#dashboardGrid .font-semibold',
                '#dashboardGrid .font-extrabold'
            ].join(',');
            return Array.from(document.querySelectorAll(selectors))
                .filter((el) => el instanceof HTMLElement)
                .filter((el) => {
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) {
                        return false;
                    }
                    if (!readableName(el)) return false;
                    if (el instanceof HTMLInputElement ||
                        el instanceof HTMLTextAreaElement ||
                        el instanceof HTMLSelectElement) {
                        return false;
                    }
                    const rect = el.getBoundingClientRect();
                    return rect.width >= 4 &&
                        rect.height >= 4 &&
                        rect.right > 0 &&
                        rect.bottom > 0 &&
                        rect.left < window.innerWidth &&
                        rect.top < window.innerHeight;
                })
                .map((el) => {
                    const rect = textRect(el) || el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return {
                        text: readableName(el).slice(0, 80),
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: String(el.className || '').slice(0, 120),
                        color: style.color,
                        fontSize: Number.parseFloat(style.fontSize) || 16,
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


def _text_box_pixel_contrast(width: int, pixels: list[tuple[int, int, int, int]], rect: dict) -> dict:
    colors: list[tuple[int, int, int]] = []
    for y in range(rect["top"], rect["bottom"]):
        for x in range(rect["left"], rect["right"]):
            red, green, blue, alpha = pixels[(y * width) + x]
            if alpha:
                colors.append((red, green, blue))
    assert colors, f"empty screenshot crop for {rect}"

    colors.sort(key=_luminance)
    low = colors[max(0, int(len(colors) * 0.05) - 1)]
    high = colors[min(len(colors) - 1, int(len(colors) * 0.95))]
    ratio = _contrast_ratio(low, high)
    low_l = _luminance(low)
    high_l = _luminance(high)
    return {
        "ratio": round(ratio, 2),
        "luminance_span": round(high_l - low_l, 3),
        "low": low,
        "high": high,
    }


@pytest.mark.parametrize("screenshot_name,screenshot_path", BASELINE_SCREENSHOTS.items())
def test_dashboard_visual_baseline_screenshot_preserves_readable_contrast(
    screenshot_name, screenshot_path
):
    assert screenshot_path.exists(), f"missing dashboard visual baseline: {screenshot_path}"
    width, height, pixels = _png_rgba_pixels(screenshot_path.read_bytes())

    assert width >= 390, f"{screenshot_name}: dashboard baseline width is too small"
    assert height >= 844, f"{screenshot_name}: dashboard baseline height is too small"

    colors = [(red, green, blue) for red, green, blue, alpha in pixels if alpha]
    colors.sort(key=_luminance)
    darkest = colors[max(0, int(len(colors) * 0.001) - 1)]
    lightest = colors[min(len(colors) - 1, int(len(colors) * 0.97))]
    contrast = _contrast_ratio(darkest, lightest)
    luminance_span = _luminance(lightest) - _luminance(darkest)
    dark_pixel_count = sum(1 for color in colors if _luminance(color) < 0.25)

    assert contrast >= 4.5, (
        f"{screenshot_name}: dashboard visual baseline contrast {contrast:.2f} < 4.5"
    )
    assert luminance_span >= 0.55, (
        f"{screenshot_name}: dashboard visual baseline luminance span "
        f"{luminance_span:.2f} is too narrow"
    )
    assert dark_pixel_count >= 1000, (
        f"{screenshot_name}: dashboard visual baseline has too few dark text pixels"
    )


@pytest.mark.parametrize("viewport_name,viewport", VIEWPORTS.items())
@pytest.mark.parametrize(
    "app_name,app,mod",
    [("jm", jm_app, jm_mod), ("my", my_app, my_mod)],
)
def test_jm_my_dashboard_screenshot_preserves_text_readability_and_contrast(
    optional_chromium_browser, viewport_name, viewport, app_name, app, mod
):
    html_response = run_async(_fetch_dashboard_html(app_name, app, mod))
    assert "대시보드" in html_response
    assert 'id="dashboardGrid"' in html_response
    assert 'id="dashboard-empty-state"' in html_response

    if optional_chromium_browser is None:
        return

    context = optional_chromium_browser.new_context(
        viewport=viewport,
        java_script_enabled=False,
        device_scale_factor=1,
    )
    page = context.new_page()
    page.set_content(_inline_render_css(app_name, html_response), wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(100)

    boxes = _visual_text_boxes(page)
    screenshot = page.screenshot(type="png", full_page=False)
    width, height, pixels = _png_rgba_pixels(screenshot)

    assert width == viewport["width"], f"{app_name} {viewport_name}: wrong screenshot width"
    assert height == viewport["height"], f"{app_name} {viewport_name}: wrong screenshot height"
    assert len(boxes) >= (36 if viewport_name == "desktop" else 24), (
        f"{app_name} {viewport_name}: too few visible dashboard text boxes: {boxes}"
    )

    sampled = []
    offenders = []
    for box in boxes:
        rect = box["rect"]
        if rect["right"] - rect["left"] < 4 or rect["bottom"] - rect["top"] < 4:
            continue
        if rect["top"] <= 1 or rect["bottom"] >= height - 1:
            continue
        stats = _text_box_pixel_contrast(width, pixels, rect)
        item = {**box, **stats}
        sampled.append(item)
        if box["fontSize"] < 10:
            continue
        required_ratio = 2.4 if box["fontSize"] >= 18 else 2.0
        if stats["ratio"] < required_ratio or stats["luminance_span"] < 0.06:
            offenders.append(item)

    assert len(sampled) >= (32 if viewport_name == "desktop" else 22), (
        f"{app_name} {viewport_name}: too few sampled dashboard text boxes: {sampled}"
    )
    assert not offenders, (
        f"{app_name} {viewport_name}: screenshot text readability/contrast regressed: "
        f"{offenders[:12]}"
    )

    page.close()
    context.close()
