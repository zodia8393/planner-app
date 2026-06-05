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
    "safe_snippet",
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
    """Render a standalone error page with Tailwind styling."""
    return f"""<!DOCTYPE html>
<html lang="ko" class="h-full">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{code}</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="h-full bg-slate-50 dark:bg-slate-900 flex items-center justify-center">
<div class="text-center px-6">
    <p class="text-7xl font-bold text-indigo-600 mb-4">{code}</p>
    <h1 class="text-2xl font-bold text-slate-800 dark:text-slate-200 mb-2">{message}</h1>
    <p class="text-slate-500 dark:text-slate-400 mb-6">잠시 후 다시 시도하거나 대시보드로 돌아가세요</p>
    <a href="/" class="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 text-white font-medium rounded-xl hover:bg-indigo-700 transition-colors">
        대시보드로 돌아가기
    </a>
</div>
</body></html>"""


def safe_snippet(value: str) -> str:
    """Escape HTML in FTS5 snippet output, preserving only <mark>/</mark> tags.

    FTS5 snippet() wraps matched terms in <mark>...</mark> but the surrounding
    text may contain user-controlled HTML that must be escaped to prevent XSS.
    """
    if not value:
        return ""
    # Replace <mark> and </mark> with unique placeholders before escaping
    _PH_OPEN = "\x00MARK_OPEN\x00"
    _PH_CLOSE = "\x00MARK_CLOSE\x00"
    s = str(value).replace("<mark>", _PH_OPEN).replace("</mark>", _PH_CLOSE)
    # Escape all remaining HTML
    s = str(markupsafe.escape(s))
    # Restore <mark> tags
    s = s.replace(_PH_OPEN, "<mark>").replace(_PH_CLOSE, "</mark>")
    return markupsafe.Markup(s)


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
    templates.env.filters["safe_snippet"] = safe_snippet
    templates.env.filters["cos_deg"] = lambda deg: round(math.cos(math.radians(deg)), 6)
    templates.env.filters["sin_deg"] = lambda deg: round(math.sin(math.radians(deg)), 6)
