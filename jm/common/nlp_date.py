"""Korean natural language date parser.

Pure-Python implementation using regex + datetime only.
No external dependencies.
"""

import calendar
import re
from datetime import date, timedelta
from typing import Optional

__all__ = [
    "parse_korean_date",
    "extract_date_from_text",
    "extract_time_from_text",
    "format_date_display",
]

# ── Day-of-week mapping ──

_WEEKDAY_FULL = {
    "월요일": 0, "화요일": 1, "수요일": 2, "목요일": 3,
    "금요일": 4, "토요일": 5, "일요일": 6,
}
_WEEKDAY_SHORT = {
    "월": 0, "화": 1, "수": 2, "목": 3,
    "금": 4, "토": 5, "일": 6,
}
_WEEKDAY_ALL = {**_WEEKDAY_FULL, **_WEEKDAY_SHORT}

_WEEKDAY_DISPLAY = ["월", "화", "수", "목", "금", "토", "일"]

# ── Korean number words ──

_KOREAN_NUMS = {
    "한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5,
    "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
}


def _parse_num(s: str) -> Optional[int]:
    """Parse a string as int, supporting Korean number words."""
    s = s.strip()
    if s.isdigit():
        return int(s)
    return _KOREAN_NUMS.get(s)


def _add_months(d: date, months: int) -> date:
    """Add (or subtract) months to a date, clamping day to valid range."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _last_day_of_month(d: date) -> date:
    """Return the last day of the month containing *d*."""
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _next_weekday(ref: date, target_wd: int) -> date:
    """Return the next occurrence of *target_wd* (0=Mon) strictly after *ref*."""
    days_ahead = target_wd - ref.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return ref + timedelta(days=days_ahead)


def _this_week_weekday(ref: date, target_wd: int) -> date:
    """Return the given weekday of the current ISO week (Mon-Sun)."""
    monday = ref - timedelta(days=ref.weekday())
    return monday + timedelta(days=target_wd)


def _next_week_weekday(ref: date, target_wd: int) -> date:
    """Return the given weekday of next week."""
    monday = ref - timedelta(days=ref.weekday()) + timedelta(weeks=1)
    return monday + timedelta(days=target_wd)


# ── Compiled patterns (order matters — more specific first) ──

# Absolute: 2026년 5월 20일 / 2026-05-20 / 2026/5/20
_PAT_ABS_FULL_KR = re.compile(
    r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일"
)
_PAT_ABS_FULL_SEP = re.compile(
    r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})"
)

# Absolute partial: 5월 20일 / 5/20 / 05-20
_PAT_ABS_PART_KR = re.compile(
    r"(\d{1,2})월\s*(\d{1,2})일"
)
_PAT_ABS_PART_SEP = re.compile(
    r"^(\d{1,2})[/\-](\d{1,2})$"
)

# Relative simple: 오늘, 내일, 모레, 글피, 어제, 그저께/그제
_PAT_RELATIVE_SIMPLE = re.compile(
    r"^(오늘|내일|모레|글피|어제|그저께|그제)$"
)

# N일/주/개월/달 후/뒤/전
_NUM_PATTERN = r"(\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)"
_PAT_RELATIVE_N = re.compile(
    rf"{_NUM_PATTERN}\s*(일|주|개월|달)\s*(후|뒤|전|이?후|이?전)"
)

# Day of week: 이번주/다음주/이번/다음 + weekday
_WEEKDAY_NAMES_RE = "|".join(
    sorted(list(_WEEKDAY_FULL.keys()) + list(_WEEKDAY_SHORT.keys()),
           key=len, reverse=True)
)
_PAT_DOW_THISWEEK = re.compile(
    rf"이번\s*주?\s*({_WEEKDAY_NAMES_RE})"
)
_PAT_DOW_NEXTWEEK = re.compile(
    rf"다음\s*주?\s*({_WEEKDAY_NAMES_RE})"
)
_PAT_DOW_NEXT = re.compile(
    rf"다음\s+({_WEEKDAY_NAMES_RE})"
)

# Shortcuts
_PAT_SHORTCUT = re.compile(
    r"^(월말|다음달\s*초|주말)$"
)

# "다음달 15일" or "이번달 20일"
_PAT_NEXT_MONTH_DAY = re.compile(
    r"(다음|이번|저번)\s*달?\s*(\d{1,2})일"
)


def parse_korean_date(text: str, reference_date: date = None) -> Optional[date]:
    """Parse Korean natural language date expression to a date object.

    Args:
        text: Korean date text (e.g. "내일", "다음주 금요일", "3일 후")
        reference_date: Base date for relative calculations (default: today)

    Returns:
        Parsed date or None if not recognized.
    """
    if not text or not isinstance(text, str):
        return None

    ref = reference_date or date.today()
    text = text.strip()

    # 1) Relative simple words
    m = _PAT_RELATIVE_SIMPLE.match(text)
    if m:
        word = m.group(1)
        offsets = {
            "오늘": 0, "내일": 1, "모레": 2, "글피": 3,
            "어제": -1, "그저께": -2, "그제": -2,
        }
        return ref + timedelta(days=offsets[word])

    # 2) Shortcuts
    m = _PAT_SHORTCUT.match(text)
    if m:
        word = m.group(1)
        if word == "월말":
            return _last_day_of_month(ref)
        elif word.startswith("다음달"):
            return _add_months(ref, 1).replace(day=1)
        elif word == "주말":
            # Next Saturday
            return _next_weekday(ref, 5)
        return None

    # 3) N일/주/개월 후/전
    m = _PAT_RELATIVE_N.match(text)
    if m:
        n = _parse_num(m.group(1))
        unit = m.group(2)
        direction_raw = m.group(3)
        if n is None:
            return None
        direction = -1 if "전" in direction_raw else 1
        if unit == "일":
            return ref + timedelta(days=n * direction)
        elif unit == "주":
            return ref + timedelta(weeks=n * direction)
        elif unit in ("개월", "달"):
            return _add_months(ref, n * direction)
        return None

    # 4) Day of week — "다음주 금요일" / "다음주 금"
    m = _PAT_DOW_NEXTWEEK.match(text)
    if m:
        wd = _WEEKDAY_ALL.get(m.group(1))
        if wd is not None:
            return _next_week_weekday(ref, wd)

    # 5) Day of week — "이번주 금요일" / "이번 금"
    m = _PAT_DOW_THISWEEK.match(text)
    if m:
        wd = _WEEKDAY_ALL.get(m.group(1))
        if wd is not None:
            return _this_week_weekday(ref, wd)

    # 6) Day of week — "다음 수요일" (without 주)
    m = _PAT_DOW_NEXT.match(text)
    if m:
        wd = _WEEKDAY_ALL.get(m.group(1))
        if wd is not None:
            return _next_week_weekday(ref, wd)

    # 6.5) "다음달 15일" / "이번달 20일" / "저번달 5일"
    m = _PAT_NEXT_MONTH_DAY.match(text)
    if m:
        prefix = m.group(1)
        day_num = int(m.group(2))
        if prefix == "다음":
            target = _add_months(ref, 1)
        elif prefix == "저번":
            target = _add_months(ref, -1)
        else:
            target = ref
        try:
            return target.replace(day=min(day_num, calendar.monthrange(target.year, target.month)[1]))
        except ValueError:
            return None

    # 7) Absolute full: 2026년 5월 20일 / 2026-05-20 / 2026/5/20
    m = _PAT_ABS_FULL_KR.match(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    m = _PAT_ABS_FULL_SEP.match(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # 8) Absolute partial: 5월 20일 / 5/20 / 05-20
    m = _PAT_ABS_PART_KR.match(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            result = date(ref.year, month, day)
        except ValueError:
            return None
        # If the date is in the past, try next year
        if result < ref:
            try:
                result = date(ref.year + 1, month, day)
            except ValueError:
                return None
        return result

    m = _PAT_ABS_PART_SEP.match(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            result = date(ref.year, month, day)
        except ValueError:
            return None
        if result < ref:
            try:
                result = date(ref.year + 1, month, day)
            except ValueError:
                return None
        return result

    return None


# ── Extraction patterns for longer sentences ──

# Ordered from most specific (longest) to least specific
_EXTRACT_PATTERNS: list[re.Pattern] = [
    # 2026년 5월 20일
    _PAT_ABS_FULL_KR,
    # 2026-05-20 / 2026/5/20
    _PAT_ABS_FULL_SEP,
    # 다음달 15일 / 이번달 20일
    _PAT_NEXT_MONTH_DAY,
    # 다음주 금요일/금
    _PAT_DOW_NEXTWEEK,
    # 이번주 금요일/금
    _PAT_DOW_THISWEEK,
    # 다음 수요일
    _PAT_DOW_NEXT,
    # N일/주/개월 후/전
    _PAT_RELATIVE_N,
    # 5월 20일
    _PAT_ABS_PART_KR,
    # 오늘/내일/모레/글피/어제/그저께
    re.compile(r"(오늘|내일|모레|글피|어제|그저께|그제)"),
    # 월말/다음달 초/주말
    re.compile(r"(월말|다음달\s*초|주말)"),
]

# Particles that can follow a date expression in Korean
_PARTICLES = re.compile(r"^(까지|에|부터|안에|이내|중으로?|전에|내로?)\s*")


def extract_date_from_text(
    text: str, reference_date: date = None
) -> tuple[Optional[date], str]:
    """Extract date expression from text, return (date, remaining_text).

    E.g. "내일까지 보고서 제출" -> (2026-05-20, "보고서 제출")
    """
    if not text or not isinstance(text, str):
        return None, text or ""

    ref = reference_date or date.today()
    text = text.strip()

    for pat in _EXTRACT_PATTERNS:
        m = pat.search(text)
        if m:
            date_str = m.group(0)
            parsed = parse_korean_date(date_str, ref)
            if parsed is not None:
                # Remove the date expression and any trailing particle
                before = text[:m.start()].strip()
                after = text[m.end():].strip()
                # Strip Korean particles (까지, 에, 부터, etc.)
                pm = _PARTICLES.match(after)
                if pm:
                    after = after[pm.end():].strip()
                remaining = f"{before} {after}".strip()
                return parsed, remaining

    return None, text


# ── Time parsing patterns ──

# "오후 3시 30분" / "오전 10시" / "오후 3시"
_PAT_TIME_AMPM = re.compile(
    r"(오전|오후)\s*(\d{1,2})시\s*(?:(\d{1,2})분)?"
)

# "3시 30분" / "15시" / "3시" (no AM/PM → default PM for 1-11)
_PAT_TIME_HOUR = re.compile(
    r"(\d{1,2})시\s*(?:(\d{1,2})분)?"
)

# "15:00" / "3:30"
_PAT_TIME_COLON = re.compile(
    r"(\d{1,2}):(\d{2})"
)

# Particles that can follow a time expression
_TIME_PARTICLES = re.compile(r"^(에|까지|부터)\s*")

_TIME_EXTRACT_PATTERNS: list[re.Pattern] = [
    _PAT_TIME_AMPM,
    _PAT_TIME_COLON,
    _PAT_TIME_HOUR,
]


def _parse_time_match(m: re.Match, pat: re.Pattern) -> Optional[str]:
    """Convert a time regex match to HH:MM string."""
    groups = m.groups()

    if pat is _PAT_TIME_AMPM:
        ampm = groups[0]
        hour = int(groups[1])
        minute = int(groups[2]) if groups[2] else 0
        if ampm == "오후" and hour < 12:
            hour += 12
        elif ampm == "오전" and hour == 12:
            hour = 0
    elif pat is _PAT_TIME_COLON:
        hour = int(groups[0])
        minute = int(groups[1])
    else:
        # _PAT_TIME_HOUR: default PM for 1-11
        hour = int(groups[0])
        minute = int(groups[1]) if groups[1] else 0
        if 1 <= hour < 12:
            hour += 12

    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def extract_time_from_text(text: str) -> tuple[Optional[str], str]:
    """Extract time expression from text, return (time_str, remaining_text).

    E.g. "오후 3시 보고서 제출" -> ("15:00", "보고서 제출")
         "15:00 회의" -> ("15:00", "회의")
         "3시 미팅" -> ("15:00", "미팅")
    """
    if not text or not isinstance(text, str):
        return None, text or ""

    text = text.strip()

    for pat in _TIME_EXTRACT_PATTERNS:
        m = pat.search(text)
        if m:
            time_str = _parse_time_match(m, pat)
            if time_str is not None:
                before = text[:m.start()].strip()
                after = text[m.end():].strip()
                # Strip Korean particles
                pm = _TIME_PARTICLES.match(after)
                if pm:
                    after = after[pm.end():].strip()
                remaining = f"{before} {after}".strip()
                return time_str, remaining

    return None, text


def format_date_display(d: date) -> str:
    """Format a date as a user-friendly Korean string.

    E.g. "5월 20일 (화)"
    """
    wd = _WEEKDAY_DISPLAY[d.weekday()]
    return f"{d.month}월 {d.day}일 ({wd})"
