"""Common utility functions shared across planner apps."""

from datetime import datetime
from typing import Optional

__all__ = [
    "fix_mojibake",
    "clamp_priority",
    "validate_date_str",
    "validate_datetime_str",
    "clamp_text",
    "safe_int",
]


def safe_int(val, default=None):
    """Safely convert a value to int, returning default on failure."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def fix_mojibake(s: str) -> str:
    """Restore UTF-8 strings mangled by Starlette latin-1 decoding."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def clamp_priority(p: int) -> int:
    return max(0, min(3, p))


def validate_date_str(d: str) -> Optional[str]:
    if not d:
        return None
    try:
        datetime.strptime(d, "%Y-%m-%d")
        return d
    except (ValueError, TypeError):
        return None


def validate_datetime_str(d: str) -> Optional[str]:
    if not d:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            datetime.strptime(d, fmt)
            return d
        except (ValueError, TypeError):
            continue
    return None


def clamp_text(s: str, maxlen: int = 500) -> str:
    return s[:maxlen] if s else ""
