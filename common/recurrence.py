"""Recurrence calculation helpers shared across planner apps.

Supports both legacy simple patterns ('daily', 'weekly', etc.) and
RFC 5545 RRULE strings (e.g. 'FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR').
"""

import calendar as cal_mod
import re
from datetime import date, timedelta
from typing import Optional

# RRULE weekday abbreviations → Python weekday (0=Mon)
_RRULE_DAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]
_FREQ_KR = {"DAILY": "매일", "WEEKLY": "매주", "MONTHLY": "매월", "YEARLY": "매년"}

# Legacy simple patterns that map directly to RRULE equivalents
_LEGACY_MAP = {
    "daily": "FREQ=DAILY",
    "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    "weekly": "FREQ=WEEKLY",
    "monthly": "FREQ=MONTHLY",
    "yearly": "FREQ=YEARLY",
}


def is_rrule(recurrence: str) -> bool:
    """Check if a recurrence string is an RRULE (vs legacy simple keyword)."""
    if not recurrence:
        return False
    return recurrence.startswith("FREQ=") or recurrence in _LEGACY_MAP


def normalize_rrule(recurrence: str) -> str:
    """Convert legacy keywords to RRULE strings; pass RRULE strings through."""
    if not recurrence or recurrence == "none":
        return ""
    if recurrence in _LEGACY_MAP:
        return _LEGACY_MAP[recurrence]
    if recurrence.startswith("FREQ="):
        return recurrence
    return ""


def parse_rrule(rrule_str: str) -> dict:
    """Parse an RRULE string into a dict of parameters.

    Returns dict with keys: freq, interval, byday, bymonthday, count, until.
    """
    result = {
        "freq": "",
        "interval": 1,
        "byday": [],
        "bymonthday": [],
        "count": None,
        "until": None,
    }
    if not rrule_str:
        return result

    # Normalize legacy patterns first
    normalized = normalize_rrule(rrule_str)
    if not normalized:
        return result

    for part in normalized.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.upper()
        if key == "FREQ":
            result["freq"] = val.upper()
        elif key == "INTERVAL":
            try:
                result["interval"] = max(1, int(val))
            except ValueError:
                pass
        elif key == "BYDAY":
            days = []
            for d in val.split(","):
                d = d.strip().upper()
                if d in _RRULE_DAY_MAP:
                    days.append(d)
            result["byday"] = days
        elif key == "BYMONTHDAY":
            days = []
            for d in val.split(","):
                try:
                    days.append(int(d.strip()))
                except ValueError:
                    pass
            result["bymonthday"] = days
        elif key == "COUNT":
            try:
                result["count"] = max(1, int(val))
            except ValueError:
                pass
        elif key == "UNTIL":
            # Accept YYYYMMDD or YYYY-MM-DD
            val = val.replace("-", "")
            if len(val) >= 8:
                try:
                    result["until"] = date(int(val[:4]), int(val[4:6]), int(val[6:8]))
                except ValueError:
                    pass
    return result


def build_rrule(freq: str, interval: int = 1, byday: list = None,
                bymonthday: list = None, count: int = None,
                until: str = None) -> str:
    """Build an RRULE string from parameters."""
    if not freq:
        return ""
    parts = [f"FREQ={freq.upper()}"]
    if interval and interval > 1:
        parts.append(f"INTERVAL={interval}")
    if byday:
        parts.append(f"BYDAY={','.join(byday)}")
    if bymonthday:
        parts.append(f"BYMONTHDAY={','.join(str(d) for d in bymonthday)}")
    if count and count > 0:
        parts.append(f"COUNT={count}")
    elif until:
        # Store as YYYYMMDD
        clean = until.replace("-", "")
        parts.append(f"UNTIL={clean}")
    return ";".join(parts)


def rrule_to_korean(rrule_str: str) -> str:
    """Convert an RRULE string to human-readable Korean text."""
    if not rrule_str or rrule_str == "none":
        return "반복 없음"

    # Check legacy simple patterns first
    legacy_kr = {
        "daily": "매일", "weekdays": "주중 매일",
        "weekly": "매주", "monthly": "매월", "yearly": "매년",
    }
    if rrule_str in legacy_kr:
        return legacy_kr[rrule_str]

    params = parse_rrule(rrule_str)
    if not params["freq"]:
        return "반복 없음"

    interval = params["interval"]
    freq = params["freq"]

    if freq == "DAILY":
        text = f"{interval}일마다" if interval > 1 else "매일"
    elif freq == "WEEKLY":
        if interval > 1:
            text = f"{interval}주마다"
        else:
            text = "매주"
        if params["byday"]:
            day_names = [_WEEKDAY_KR[_RRULE_DAY_MAP[d]] for d in params["byday"]
                         if d in _RRULE_DAY_MAP]
            if day_names:
                text += " " + ",".join(day_names)
    elif freq == "MONTHLY":
        if interval > 1:
            text = f"{interval}개월마다"
        else:
            text = "매월"
        if params["bymonthday"]:
            text += " " + ",".join(f"{d}일" for d in params["bymonthday"])
    elif freq == "YEARLY":
        text = f"{interval}년마다" if interval > 1 else "매년"
    else:
        text = rrule_str

    # End condition
    if params["count"]:
        text += f" ({params['count']}회)"
    elif params["until"]:
        text += f" (~{params['until'].isoformat()})"

    return text


def _add_months(d: date, months: int) -> date:
    """Add N months to a date, clamping day to valid range."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, cal_mod.monthrange(year, month)[1])
    return date(year, month, day)


def _next_by_rrule(current: date, params: dict) -> Optional[date]:
    """Calculate next occurrence from parsed RRULE params."""
    freq = params["freq"]
    interval = params["interval"]

    if freq == "DAILY":
        return current + timedelta(days=interval)

    elif freq == "WEEKLY":
        byday = params["byday"]
        if not byday:
            # Simple weekly with interval
            return current + timedelta(weeks=interval)
        # Find next matching weekday
        target_weekdays = sorted(_RRULE_DAY_MAP[d] for d in byday if d in _RRULE_DAY_MAP)
        if not target_weekdays:
            return current + timedelta(weeks=interval)

        cur_wd = current.weekday()
        # Look for next day in same week (after current)
        for wd in target_weekdays:
            if wd > cur_wd:
                return current + timedelta(days=wd - cur_wd)
        # Wrap to first day of next interval-week
        days_to_monday = 7 - cur_wd  # days to next Monday
        next_monday = current + timedelta(days=days_to_monday + 7 * (interval - 1))
        return next_monday + timedelta(days=target_weekdays[0])

    elif freq == "MONTHLY":
        bymonthday = params["bymonthday"]
        if not bymonthday:
            return _add_months(current, interval)
        # Find next matching day in current or future month
        targets = sorted(bymonthday)
        # Check remaining days this month
        for day_num in targets:
            if day_num > current.day:
                max_day = cal_mod.monthrange(current.year, current.month)[1]
                if day_num <= max_day:
                    return date(current.year, current.month, day_num)
        # Move to next interval-month
        next_m = _add_months(current, interval)
        first_of_month = date(next_m.year, next_m.month, 1)
        max_day = cal_mod.monthrange(first_of_month.year, first_of_month.month)[1]
        target_day = min(targets[0], max_day)
        return date(first_of_month.year, first_of_month.month, target_day)

    elif freq == "YEARLY":
        try:
            return date(current.year + interval, current.month, current.day)
        except ValueError:
            # Feb 29 in non-leap year
            return date(current.year + interval, current.month, 28)

    return None


def next_occurrence(current_date_str: str, recurrence: str) -> Optional[str]:
    """Calculate the next occurrence date from current_date and recurrence pattern.

    Supports both legacy patterns ('daily', 'weekly', etc.) and RRULE strings.
    Returns ISO date string or None if no next occurrence.
    """
    if not current_date_str or not recurrence or recurrence == "none":
        return None
    try:
        current = date.fromisoformat(current_date_str)
    except (ValueError, TypeError):
        return None

    # Parse RRULE (handles both legacy and RRULE formats)
    params = parse_rrule(recurrence)
    if not params["freq"]:
        return None

    nxt = _next_by_rrule(current, params)
    if nxt is None:
        return None

    # Check COUNT and UNTIL limits
    if params["until"] and nxt > params["until"]:
        return None

    return nxt.isoformat()


def expand_recurring(start_date_str: str, rrule_str: str,
                     range_start_str: str, range_end_str: str) -> list[str]:
    """Expand a recurrence rule into a list of ISO date strings within a range.

    Args:
        start_date_str: The original start date of the recurring item.
        rrule_str: The recurrence pattern (legacy or RRULE).
        range_start_str: Start of the display range.
        range_end_str: End of the display range.

    Returns:
        List of ISO date strings within [range_start, range_end].
    """
    try:
        start = date.fromisoformat(start_date_str)
        range_start = date.fromisoformat(range_start_str)
        range_end = date.fromisoformat(range_end_str)
    except (ValueError, TypeError):
        return []

    params = parse_rrule(rrule_str)
    if not params["freq"]:
        return []

    results = []
    cur = start
    count_limit = params.get("count")
    count_so_far = 0
    max_iterations = 1000  # safety limit

    for _ in range(max_iterations):
        if cur > range_end:
            break
        if params["until"] and cur > params["until"]:
            break
        if count_limit and count_so_far >= count_limit:
            break

        if cur >= range_start:
            results.append(cur.isoformat())

        count_so_far += 1
        nxt_str = next_occurrence(cur.isoformat(), rrule_str)
        if not nxt_str:
            break
        nxt = date.fromisoformat(nxt_str)
        if nxt <= cur:
            break
        cur = nxt

    return results


def expand_recurring_events(events_list: list, start_date: str, end_date: str) -> list:
    """Expand recurring events into individual occurrences for calendar display.

    Compatible with both legacy patterns and RRULE strings.
    """
    result = []
    try:
        range_start = date.fromisoformat(start_date)
        range_end = date.fromisoformat(end_date)
    except (ValueError, TypeError):
        return events_list

    for ev in events_list:
        rec = ev.get("recurrence", "")
        if not rec:
            result.append(ev)
            continue
        rec_end_str = ev.get("recurrence_end", "")
        rec_end = date.fromisoformat(rec_end_str) if rec_end_str else None
        orig_start = ev.get("start_time", "")[:10] if ev.get("start_time") else ""
        if not orig_start:
            result.append(ev)
            continue
        try:
            cur = date.fromisoformat(orig_start)
        except (ValueError, TypeError):
            result.append(ev)
            continue
        time_part = ev.get("start_time", "")[10:] if len(ev.get("start_time", "")) > 10 else ""
        end_time_val = ev.get("end_time", "")
        if end_time_val and len(end_time_val) >= 10:
            try:
                orig_end_date = date.fromisoformat(end_time_val[:10])
                day_offset = (orig_end_date - cur).days
                end_time_suffix = end_time_val[10:]
            except (ValueError, TypeError):
                day_offset = 0
                end_time_suffix = ""
        else:
            day_offset = 0
            end_time_suffix = ""

        # Parse RRULE params once to check COUNT
        params = parse_rrule(rec)
        count_limit = params.get("count")
        count_so_far = 0

        while cur <= range_end:
            if rec_end and cur > rec_end:
                break
            if params.get("until") and cur > params["until"]:
                break
            if count_limit and count_so_far >= count_limit:
                break
            if cur >= range_start:
                occ = dict(ev)
                occ["start_time"] = cur.isoformat() + time_part
                if end_time_val:
                    occ_end = cur + timedelta(days=day_offset)
                    occ["end_time"] = occ_end.isoformat() + end_time_suffix
                occ["is_recurring_instance"] = True
                occ["_original_id"] = ev.get("id")
                result.append(occ)
            count_so_far += 1
            nxt = next_occurrence(cur.isoformat(), rec)
            if not nxt:
                break
            new_cur = date.fromisoformat(nxt)
            if new_cur <= cur:
                break
            cur = new_cur

    return result
