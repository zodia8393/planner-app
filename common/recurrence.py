"""Recurrence calculation helpers shared across planner apps."""

import calendar as cal_mod
from datetime import date, timedelta
from typing import Optional


def next_occurrence(current_date_str: str, recurrence: str) -> Optional[str]:
    if not current_date_str or not recurrence or recurrence == "none":
        return None
    try:
        d = date.fromisoformat(current_date_str)
    except (ValueError, TypeError):
        return None
    if recurrence == "daily":
        d += timedelta(days=1)
    elif recurrence == "weekdays":
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    elif recurrence == "weekly":
        d += timedelta(weeks=1)
    elif recurrence == "monthly":
        month = d.month + 1
        year = d.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(d.day, cal_mod.monthrange(year, month)[1])
        d = date(year, month, day)
    elif recurrence == "yearly":
        try:
            d = date(d.year + 1, d.month, d.day)
        except ValueError:
            d = date(d.year + 1, d.month, 28)
    else:
        return None
    return d.isoformat()


def expand_recurring_events(events_list: list, start_date: str, end_date: str) -> list:
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
        while cur <= range_end:
            if rec_end and cur > rec_end:
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
            nxt = next_occurrence(cur.isoformat(), rec)
            if not nxt:
                break
            new_cur = date.fromisoformat(nxt)
            if new_cur <= cur:
                break
            cur = new_cur

    return result
