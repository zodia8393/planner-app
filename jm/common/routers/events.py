import calendar as cal_mod
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from common.holidays import get_holidays_for_month, get_holidays_for_year
from common.recurrence import expand_recurring_events
from common.utils import clamp_text, fix_mojibake, validate_date_str, validate_datetime_str

router = APIRouter()


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, year: Optional[int] = None, month: Optional[int] = None, view: str = "month"):
    S = request.app.state
    pid = S.get_profile_id(request)
    today = date.today()
    y = year or today.year
    m = month or today.month

    if m < 1:
        m = 12; y -= 1
    elif m > 12:
        m = 1; y += 1

    # ── Year view: 12 months in one screen ──
    if view == "year":
        year_start = f"{y}-01-01"
        year_end = f"{y}-12-31"
        with S.get_db() as conn:
            events = conn.execute("""
                SELECT e.*, c.name as category_name
                FROM events e LEFT JOIN categories c ON e.category_id = c.id
                WHERE e.profile_id = ?
                  AND (
                    (COALESCE(e.recurrence, '') = '' AND date(e.start_time) BETWEEN ? AND ?)
                    OR (COALESCE(e.recurrence, '') != '' AND date(e.start_time) <= ?)
                  )
                ORDER BY e.start_time ASC
            """, (pid, year_start, year_end, year_end)).fetchall()

            todos = conn.execute("""
                SELECT t.due_date, t.completed
                FROM todos t
                WHERE t.due_date BETWEEN ? AND ? AND t.profile_id = ?
            """, (year_start, year_end, pid)).fetchall()

            categories = S.get_categories(conn, pid)

        all_events = expand_recurring_events([dict(ev) for ev in events], year_start, year_end)

        # Build a set of dates that have events (with color info)
        event_dates: dict = {}  # date_str -> list of colors
        for ev in all_events:
            try:
                day_key = ev["start_time"][:10]
            except (TypeError, IndexError):
                continue
            event_dates.setdefault(day_key, []).append(ev.get("color", "#6366f1"))

        todo_dates: set = set()
        for td in todos:
            dd = td["due_date"]
            if dd:
                todo_dates.add(dd)

        # Build 12 months of data
        months_data = []
        for mi in range(1, 13):
            _, dim = cal_mod.monthrange(y, mi)
            fd = date(y, mi, 1)
            sun_start = (fd.weekday() + 1) % 7  # Sunday-start offset
            months_data.append({
                "month": mi,
                "days_in_month": dim,
                "sun_start": sun_start,
            })

        return S.render(request, "calendar.html", {
            "page": "calendar",
            "year": y,
            "month": m,
            "cal_view": "year",
            "months_data": months_data,
            "event_dates": event_dates,
            "todo_dates": todo_dates,
            "today_str": today.isoformat(),
            "holidays_by_date": get_holidays_for_year(y),
            "categories": [dict(c) for c in categories],
            # Needed for the event modal in year view
            "days_in_month": 0,
            "start_weekday": 0,
            "events_by_date": {},
            "todos_by_date": {},
            "prev_year": y - 1,
            "prev_month": m,
            "next_year": y + 1,
            "next_month": m,
            "week_days": [],
        })

    first_day = date(y, m, 1)
    _, days_in_month = cal_mod.monthrange(y, m)
    start_weekday = first_day.weekday()

    month_start = first_day.isoformat()
    month_end = date(y, m, days_in_month).isoformat()

    with S.get_db() as conn:
        # Fetch non-recurring events in range + all recurring events that started on or before month end
        events = conn.execute("""
            SELECT e.*, c.name as category_name
            FROM events e LEFT JOIN categories c ON e.category_id = c.id
            WHERE e.profile_id = ?
              AND (
                (COALESCE(e.recurrence, '') = '' AND date(e.start_time) BETWEEN ? AND ?)
                OR (COALESCE(e.recurrence, '') != '' AND date(e.start_time) <= ?)
              )
            ORDER BY e.start_time ASC
        """, (pid, month_start, month_end, month_end)).fetchall()

        todos = conn.execute("""
            SELECT t.*, c.name as category_name, c.color as category_color
            FROM todos t LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.due_date BETWEEN ? AND ?
              AND t.profile_id = ?
            ORDER BY t.priority ASC, t.sort_order ASC
        """, (month_start, month_end, pid)).fetchall()

        categories = S.get_categories(conn, pid)

    # Expand recurring events into individual occurrences
    all_events = expand_recurring_events([dict(ev) for ev in events], month_start, month_end)

    events_by_date: dict = {}
    for d in all_events:
        try:
            day_key = d["start_time"][:10]
        except (TypeError, IndexError):
            continue
        events_by_date.setdefault(day_key, []).append(d)

    # Merge Google Calendar events if the app provides gcal support
    gcal_fetch = getattr(S, "gcal_fetch_events", None)
    if gcal_fetch:
        gcal_events = await gcal_fetch(pid, month_start, month_end)
        for gev in gcal_events:
            day_key = gev["start_time"][:10] if gev["start_time"] else ""
            if day_key:
                events_by_date.setdefault(day_key, []).append(gev)

    todos_by_date: dict = {}
    for td in todos:
        d = dict(td)
        dd = d.get("due_date", "")
        if dd:
            todos_by_date.setdefault(dd, []).append(d)

    prev_m, prev_y = m - 1, y
    if prev_m < 1:
        prev_m = 12; prev_y -= 1
    next_m, next_y = m + 1, y
    if next_m > 12:
        next_m = 1; next_y += 1

    # Item 15: Week view data
    from datetime import timedelta as _td
    week_start = today - _td(days=today.weekday())
    week_days = []
    for i in range(7):
        d = week_start + _td(days=i)
        d_str = d.isoformat()
        week_days.append({
            "date": d, "date_str": d_str,
            "events": events_by_date.get(d_str, []),
            "todos": todos_by_date.get(d_str, []),
            "is_today": d == today,
        })

    return S.render(request, "calendar.html", {
        "page": "calendar",
        "year": y,
        "month": m,
        "days_in_month": days_in_month,
        "start_weekday": start_weekday,
        "events_by_date": events_by_date,
        "todos_by_date": todos_by_date,
        "categories": [dict(c) for c in categories],
        "prev_year": prev_y,
        "prev_month": prev_m,
        "next_year": next_y,
        "next_month": next_m,
        "today_str": today.isoformat(),
        "holidays_by_date": get_holidays_for_month(y, m),
        "cal_view": view,
        "week_days": week_days,
    })


@router.post("/events", response_class=HTMLResponse)
async def create_event(request: Request,
                       title: str = Form(""),
                       start_time: str = Form(""),
                       end_time: str = Form(""),
                       color: str = Form("#6366f1"),
                       category_id: str = Form(""),
                       memo: str = Form(""),
                       recurrence: str = Form(""),
                       recurrence_end: str = Form(""),
                       also_todo: str = Form(""),
                       reminder_offsets: str = Form(""),
                       return_year: str = Form(""),
                       return_month: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200).strip()
    if not title:
        return S.redirect(request, "/calendar")
    memo = clamp_text(fix_mojibake(memo), 2000)
    start_time = validate_datetime_str(start_time) or datetime.now().strftime("%Y-%m-%dT%H:%M")
    end_time = validate_datetime_str(end_time)
    if start_time and end_time and end_time < start_time:
        start_time, end_time = end_time, start_time
    cat_id = int(category_id) if category_id else None
    recurrence_end = validate_date_str(recurrence_end) or ""

    # Parse reminder_offsets (JSON string or empty for global default)
    r_offsets = reminder_offsets.strip() if reminder_offsets else None
    if r_offsets == "[]" or r_offsets == "":
        r_offsets = None

    # Push to Google Calendar if available
    gcal_push = getattr(S, "gcal_push_event", None)
    gcal_id = await gcal_push(pid, title, start_time, end_time or "") if gcal_push else ""

    with S.get_db() as conn:
        conn.execute("""
            INSERT INTO events (title, start_time, end_time, color, category_id, memo, profile_id, gcal_event_id, recurrence, recurrence_end, reminder_offsets)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, start_time, end_time, color, cat_id, memo, pid, gcal_id, recurrence, recurrence_end, r_offsets))

        if also_todo:
            event_date = start_time[:10] if start_time else ""
            due = validate_date_str(event_date)
            max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
            conn.execute("""
                INSERT INTO todos (title, due_date, priority, category_id, repeat_type, sort_order, profile_id)
                VALUES (?, ?, 2, ?, 'none', ?, ?)
            """, (title, due, cat_id, max_order + 1, pid))

    S.event_bus.emit("event", {"action": "created", "title": title})
    redirect_url = "/calendar"
    if return_year and return_month:
        redirect_url = f"/calendar?year={return_year}&month={return_month}"
    return S.redirect(request, redirect_url)


@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
async def edit_event_form(request: Request, event_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        event = conn.execute("SELECT * FROM events WHERE id=? AND profile_id=?", (event_id, pid)).fetchone()
        if not event:
            return HTMLResponse("")
        categories = S.get_categories(conn, pid)
    ev_dict = dict(event)
    # Extract year/month from event start_time for return redirect
    try:
        ev_year = int(ev_dict["start_time"][:4])
        ev_month = int(ev_dict["start_time"][5:7])
    except (TypeError, ValueError, IndexError):
        ev_year = date.today().year
        ev_month = date.today().month
    return S.render(request, "partials/event_edit_form.html", {
        "event": ev_dict,
        "categories": [dict(c) for c in categories],
        "return_year": ev_year,
        "return_month": ev_month,
    })


@router.put("/events/{event_id}", response_class=HTMLResponse)
async def update_event(request: Request, event_id: int,
                       title: str = Form(""),
                       start_time: str = Form(""),
                       end_time: str = Form(""),
                       color: str = Form("#6366f1"),
                       category_id: str = Form(""),
                       memo: str = Form(""),
                       recurrence: str = Form(""),
                       recurrence_end: str = Form(""),
                       reminder_offsets: str = Form(""),
                       return_year: str = Form(""),
                       return_month: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    memo = clamp_text(fix_mojibake(memo), 2000)
    start_time = validate_datetime_str(start_time) or datetime.now().strftime("%Y-%m-%dT%H:%M")
    end_time = validate_datetime_str(end_time)
    cat_id = int(category_id) if category_id else None
    recurrence_end = validate_date_str(recurrence_end) or ""

    r_offsets = reminder_offsets.strip() if reminder_offsets else None
    if r_offsets == "[]" or r_offsets == "":
        r_offsets = None

    with S.get_db() as conn:
        row = conn.execute("SELECT gcal_event_id FROM events WHERE id=? AND profile_id=?", (event_id, pid)).fetchone()
        gcal_id = row["gcal_event_id"] if row and row["gcal_event_id"] else ""
        conn.execute("""
            UPDATE events SET title=?, start_time=?, end_time=?, color=?, category_id=?, memo=?,
                   recurrence=?, recurrence_end=?, reminder_offsets=?, updated_at=datetime('now','localtime')
            WHERE id=? AND profile_id=?
        """, (title, start_time, end_time, color, cat_id, memo, recurrence, recurrence_end, r_offsets, event_id, pid))

    gcal_update = getattr(S, "gcal_update_event", None)
    if gcal_update and gcal_id:
        await gcal_update(pid, gcal_id, title, start_time, end_time or "")

    S.event_bus.emit("event", {"action": "updated", "id": event_id, "title": title})
    redirect_url = "/calendar"
    if return_year and return_month:
        redirect_url = f"/calendar?year={return_year}&month={return_month}"
    return S.redirect(request, redirect_url)


@router.delete("/events/{event_id}", response_class=HTMLResponse)
async def delete_event(request: Request, event_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        row = conn.execute("SELECT gcal_event_id FROM events WHERE id=? AND profile_id=?", (event_id, pid)).fetchone()
        gcal_id = row["gcal_event_id"] if row and row["gcal_event_id"] else ""
        conn.execute("DELETE FROM events WHERE id=? AND profile_id=?", (event_id, pid))

    gcal_delete = getattr(S, "gcal_delete_event", None)
    if gcal_delete and gcal_id:
        await gcal_delete(pid, gcal_id)

    S.event_bus.emit("event", {"action": "deleted", "id": event_id})
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return S.redirect(request, "/calendar")
