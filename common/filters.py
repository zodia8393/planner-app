"""Common Jinja2 template filters for planner apps.

Extracted from jm/main.py and my/main.py to avoid duplication.
Usage:
    from common.filters import register_filters
    register_filters(templates)
"""

import json
import math
import re
from datetime import datetime, date

import markupsafe

__all__ = [
    "format_date",
    "format_datetime",
    "relative_date",
    "parse_tags",
    "nl2br",
    "format_number",
    "format_filesize",
    "render_worklog_images",
    "render_error_page",
    "register_filters",
]


def format_date(value: str, fmt: str | None = None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
        if fmt:
            return dt.strftime(fmt)
        return f"{dt.month}월 {dt.day}일"
    except (ValueError, TypeError):
        return str(value)


def format_datetime(value: str, fmt: str | None = None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except (ValueError, TypeError):
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return str(value)
    if fmt:
        return dt.strftime(fmt)
    return f"{dt.month}월 {dt.day}일 {dt.strftime('%H:%M')}"


def relative_date(value: str) -> str:
    if not value:
        return ""
    try:
        target = datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return str(value)
    today = date.today()
    diff = (target - today).days
    if diff == 0:
        return "오늘"
    elif diff == 1:
        return "내일"
    elif diff == -1:
        return "어제"
    elif diff < 0:
        return f"{-diff}일 전"
    elif diff <= 7:
        return f"{diff}일 후"
    else:
        return f"{target.month}월 {target.day}일"


def parse_tags(value: str) -> list:
    if not value or value == "[]":
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return [t.strip() for t in str(value).split(",") if t.strip()]


def nl2br(value: str) -> str:
    if not value:
        return ""
    return markupsafe.Markup(str(markupsafe.escape(value)).replace("\n", "<br>"))


def format_number(value) -> str:
    """Format number with thousand separators."""
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value)


def format_filesize(value) -> str:
    """Format byte count as human-readable file size."""
    try:
        b = int(value)
    except (ValueError, TypeError):
        return str(value)
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / (1024 * 1024):.1f} MB"


def render_error_page(code: int, message: str) -> str:
    """Render a standalone error page with inline CSS (no CDN dependency)."""
    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{code}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#faf9f7;color:#1c1917}}
@media(prefers-color-scheme:dark){{body{{background:#1c1917;color:#fafaf9}}
.err-code{{color:#f59e0b}}.err-msg{{color:#e7e5e4}}.err-sub{{color:#a8a29e}}
.err-btn{{background:#f59e0b;color:#1c1917}}.err-btn:hover{{background:#d97706}}}}
.err-wrap{{text-align:center;padding:1.5rem}}
.err-code{{font-size:4.5rem;font-weight:800;color:#d97706;margin-bottom:0.75rem}}
.err-msg{{font-size:1.25rem;font-weight:700;margin-bottom:0.5rem}}
.err-sub{{font-size:0.875rem;color:#78716c;margin-bottom:1.5rem}}
.err-btn{{display:inline-flex;align-items:center;gap:0.5rem;padding:0.75rem 1.5rem;
background:#d97706;color:#fff;font-weight:600;border-radius:0.75rem;
text-decoration:none;transition:background 0.2s}}
.err-btn:hover{{background:#b45309}}
.err-btn svg{{width:1.25rem;height:1.25rem}}
</style>
</head>
<body>
<div class="err-wrap">
    <p class="err-code">{code}</p>
    <h1 class="err-msg">{message}</h1>
    <p class="err-sub">잠시 후 다시 시도하거나 대시보드로 돌아가세요</p>
    <a href="/" class="err-btn">
        <svg fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18"/></svg>
        대시보드로 돌아가기
    </a>
</div>
</body></html>"""


def render_worklog_images(content):
    """Convert markdown image syntax to HTML img tags for worklog content."""
    if not content:
        return ""
    safe = str(markupsafe.escape(content))
    safe = re.sub(
        r'!\[([^\]]*)\]\((/worklog-images/[^)]+)\)',
        r'<img src="\2" alt="\1" class="max-w-full rounded-lg my-2 border" style="max-height:400px">',
        safe,
    )
    return markupsafe.Markup(safe)


def register_filters(templates) -> None:
    """Register all common filters on a Jinja2Templates instance.

    Args:
        templates: A ``fastapi.templating.Jinja2Templates`` (or any object
                   whose ``.env`` attribute is a Jinja2 ``Environment``).
    """
    templates.env.filters["format_date"] = format_date
    templates.env.filters["format_datetime"] = format_datetime
    templates.env.filters["relative_date"] = relative_date
    templates.env.filters["parse_tags"] = parse_tags
    templates.env.filters["nl2br"] = nl2br
    templates.env.filters["format_number"] = format_number
    templates.env.filters["format_filesize"] = format_filesize
    templates.env.filters["render_images"] = render_worklog_images
    templates.env.filters["cos_deg"] = lambda deg: round(math.cos(math.radians(deg)), 6)
    templates.env.filters["sin_deg"] = lambda deg: round(math.sin(math.radians(deg)), 6)
