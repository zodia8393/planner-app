import calendar as cal_mod
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from common.holidays import get_holidays_for_month
from common.recurrence import expand_recurring_events
from common.utils import clamp_text, fix_mojibake, validate_date_str, validate_datetime_str

router = APIRouter()


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    S = request.app.state
    pid = S.get_profile_id(request)
    today = date.today()
    y = year or today.year
    m = month or today.month

    if m < 1:
        m = 12; y -= 1
    elif m > 12:
        m = 1; y += 1

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
    })


@router.post("/events", response_class=HTMLResponse)
async def create_event(request: Request,
                       title: str = Form(...),
                       start_time: str = Form(...),
                       end_time: str = Form(""),
                       color: str = Form("#6366f1"),
                       category_id: str = Form(""),
                       memo: str = Form(""),
                       recurrence: str = Form(""),
                       recurrence_end: str = Form(""),
                       also_todo: str = Form("")):
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

    # Push to Google Calendar if available
    gcal_push = getattr(S, "gcal_push_event", None)
    gcal_id = await gcal_push(pid, title, start_time, end_time or "") if gcal_push else ""

    with S.get_db() as conn:
        conn.execute("""
            INSERT INTO events (title, start_time, end_time, color, category_id, memo, profile_id, gcal_event_id, recurrence, recurrence_end)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, start_time, end_time, color, cat_id, memo, pid, gcal_id, recurrence, recurrence_end))

        if also_todo:
            event_date = start_time[:10] if start_time else ""
            due = validate_date_str(event_date)
            max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM todos WHERE profile_id=?", (pid,)).fetchone()[0]
            conn.execute("""
                INSERT INTO todos (title, due_date, priority, category_id, repeat_type, sort_order, profile_id)
                VALUES (?, ?, 2, ?, 'none', ?, ?)
            """, (title, due, cat_id, max_order + 1, pid))

    S.event_bus.emit("event", {"action": "created", "title": title})
    return S.redirect(request, "/calendar")


@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
async def edit_event_form(request: Request, event_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        event = conn.execute("SELECT * FROM events WHERE id=? AND profile_id=?", (event_id, pid)).fetchone()
        if not event:
            raise HTTPException(404)
        categories = S.get_categories(conn, pid)
    return S.render(request, "partials/event_edit_form.html", {
        "event": dict(event),
        "categories": [dict(c) for c in categories],
    })


@router.put("/events/{event_id}", response_class=HTMLResponse)
async def update_event(request: Request, event_id: int,
                       title: str = Form(...),
                       start_time: str = Form(...),
                       end_time: str = Form(""),
                       color: str = Form("#6366f1"),
                       category_id: str = Form(""),
                       memo: str = Form(""),
                       recurrence: str = Form(""),
                       recurrence_end: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    memo = clamp_text(fix_mojibake(memo), 2000)
    start_time = validate_datetime_str(start_time) or datetime.now().strftime("%Y-%m-%dT%H:%M")
    end_time = validate_datetime_str(end_time)
    cat_id = int(category_id) if category_id else None
    recurrence_end = validate_date_str(recurrence_end) or ""

    with S.get_db() as conn:
        row = conn.execute("SELECT gcal_event_id FROM events WHERE id=? AND profile_id=?", (event_id, pid)).fetchone()
        gcal_id = row["gcal_event_id"] if row and row["gcal_event_id"] else ""
        conn.execute("""
            UPDATE events SET title=?, start_time=?, end_time=?, color=?, category_id=?, memo=?,
                   recurrence=?, recurrence_end=?, updated_at=datetime('now','localtime')
            WHERE id=? AND profile_id=?
        """, (title, start_time, end_time, color, cat_id, memo, recurrence, recurrence_end, event_id, pid))

    gcal_update = getattr(S, "gcal_update_event", None)
    if gcal_update and gcal_id:
        await gcal_update(pid, gcal_id, title, start_time, end_time or "")

    S.event_bus.emit("event", {"action": "updated", "id": event_id, "title": title})
    return S.redirect(request, "/calendar")


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
