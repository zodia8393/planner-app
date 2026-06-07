"""Google Calendar OAuth + event edit/delete router."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from common.utils import clamp_text, fix_mojibake
from common.gcal import (
    GCAL_CLIENT_ID, GCAL_CLIENT_SECRET, GCAL_SCOPES, GCAL_AUTH_URL,
    GCAL_TOKEN_URL, GCAL_API_BASE,
    gcal_redirect_uri as _gcal_redirect_uri,
)

router = APIRouter()


# ── Google Calendar Event Edit/Delete ──

@router.get("/events/gcal/{gcal_id:path}/edit", response_class=HTMLResponse)
async def edit_gcal_event_form(request: Request, gcal_id: str):
    """Fetch a Google Calendar event and return an edit form."""
    S = request.app.state
    pid = S.get_profile_id(request)
    import httpx
    token = await S.gcal_refresh_token(pid) if hasattr(S, "gcal_refresh_token") else None
    if not token:
        raise HTTPException(400, "Google Calendar not connected")
    with S.get_db() as conn:
        row = conn.execute("SELECT calendar_id FROM gcal_tokens WHERE profile_id=?", (pid,)).fetchone()
    cal_id = row["calendar_id"] if row else "primary"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GCAL_API_BASE}/calendars/{cal_id}/events/{gcal_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(404, "Event not found")
    ev = resp.json()
    start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
    end = ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", ""))
    if "T" in start and "+" in start:
        start = start.rsplit("+", 1)[0]
    if "T" in end and "+" in end:
        end = end.rsplit("+", 1)[0]
    event_data = {
        "gcal_id": gcal_id,
        "title": ev.get("summary", ""),
        "start_time": start,
        "end_time": end,
        "memo": ev.get("description", ""),
        "color": "#4285F4",
    }
    return S.render(request, "partials/gcal_event_edit_form.html", {"event": event_data})


@router.put("/events/gcal/{gcal_id:path}", response_class=HTMLResponse)
async def update_gcal_event(request: Request, gcal_id: str,
                            title: str = Form(""),
                            start_time: str = Form(""),
                            end_time: str = Form(""),
                            memo: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 200)
    if not title or not start_time:
        return S.redirect(request, "/calendar")
    memo = clamp_text(fix_mojibake(memo), 2000)
    import httpx
    token = await S.gcal_refresh_token(pid) if hasattr(S, "gcal_refresh_token") else None
    if not token:
        raise HTTPException(400, "Google Calendar not connected")
    with S.get_db() as conn:
        row = conn.execute("SELECT calendar_id FROM gcal_tokens WHERE profile_id=?", (pid,)).fetchone()
    cal_id = row["calendar_id"] if row else "primary"
    body = {"summary": title, "description": memo}
    if "T" in start_time:
        body["start"] = {"dateTime": start_time + ":00+09:00" if len(start_time) == 16 else start_time, "timeZone": "Asia/Seoul"}
        if end_time and "T" in end_time:
            body["end"] = {"dateTime": end_time + ":00+09:00" if len(end_time) == 16 else end_time, "timeZone": "Asia/Seoul"}
        else:
            body["end"] = body["start"]
    else:
        body["start"] = {"date": start_time[:10]}
        body["end"] = {"date": (end_time[:10] if end_time else start_time[:10])}
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{GCAL_API_BASE}/calendars/{cal_id}/events/{gcal_id}",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    return S.redirect(request, "/calendar")


@router.delete("/events/gcal/{gcal_id:path}", response_class=HTMLResponse)
async def delete_gcal_event(request: Request, gcal_id: str):
    S = request.app.state
    pid = S.get_profile_id(request)
    import httpx
    token = await S.gcal_refresh_token(pid) if hasattr(S, "gcal_refresh_token") else None
    if not token:
        raise HTTPException(400, "Google Calendar not connected")
    with S.get_db() as conn:
        row = conn.execute("SELECT calendar_id FROM gcal_tokens WHERE profile_id=?", (pid,)).fetchone()
    cal_id = row["calendar_id"] if row else "primary"
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{GCAL_API_BASE}/calendars/{cal_id}/events/{gcal_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return S.redirect(request, "/calendar")


# ── Google Calendar OAuth ──

@router.get("/settings/gcal/connect")
async def gcal_connect(request: Request):
    S = request.app.state
    if not GCAL_CLIENT_ID:
        raise HTTPException(400, "GCAL_CLIENT_ID 환경변수가 설정되지 않았습니다")
    from urllib.parse import urlencode
    pid = S.get_profile_id(request)
    params = urlencode({
        "client_id": GCAL_CLIENT_ID,
        "redirect_uri": _gcal_redirect_uri(request),
        "response_type": "code",
        "scope": GCAL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": str(pid),
    })
    return RedirectResponse(f"{GCAL_AUTH_URL}?{params}")


@router.get("/settings/gcal/callback")
async def gcal_callback(request: Request, code: str = "", error: str = "", state: str = ""):
    S = request.app.state
    import httpx
    logger = logging.getLogger("gcal")
    logger.info(f"[GCAL] callback: code={'yes' if code else 'NO'}, error={error}, state={state}")
    if error:
        logger.error(f"[GCAL] Google returned error: {error}")
        raise HTTPException(400, f"Google 인증 오류: {error}")
    if not code:
        logger.error("[GCAL] No code received")
        raise HTTPException(400, "Google 인증 코드가 없습니다")
    pid = int(state) if state.isdigit() else S.get_profile_id(request)
    redirect_uri = _gcal_redirect_uri(request)
    logger.info(f"[GCAL] token exchange: pid={pid}, redirect_uri={redirect_uri}")
    async with httpx.AsyncClient() as client:
        resp = await client.post(GCAL_TOKEN_URL, data={
            "code": code,
            "client_id": GCAL_CLIENT_ID,
            "client_secret": GCAL_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
    if resp.status_code != 200:
        logger.error(f"[GCAL] token exchange failed: {resp.status_code} {resp.text[:300]}")
        raise HTTPException(400, f"Google 토큰 교환 실패: {resp.text[:200]}")
    data = resp.json()
    logger.info(f"[GCAL] token received, expires_in={data.get('expires_in')}")
    expiry = (datetime.now() + timedelta(seconds=data["expires_in"])).isoformat()
    with S.get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO gcal_tokens (profile_id, access_token, refresh_token, token_expiry)
            VALUES (?, ?, ?, ?)
        """, (pid, data["access_token"], data.get("refresh_token", ""), expiry))
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/gcal/disconnect")
async def gcal_disconnect(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM gcal_tokens WHERE profile_id=?", (pid,))
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/gcal/calendar-id")
async def gcal_set_calendar_id(request: Request, calendar_id: str = Form("primary")):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("UPDATE gcal_tokens SET calendar_id=? WHERE profile_id=?", (calendar_id, pid))
    return RedirectResponse("/settings", status_code=303)


@router.get("/api/gcal/calendars")
async def gcal_list_calendars(request: Request):
    S = request.app.state
    import httpx
    pid = S.get_profile_id(request)
    token = await S.gcal_refresh_token(pid) if hasattr(S, "gcal_refresh_token") else None
    if not token:
        return JSONResponse([])
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GCAL_API_BASE}/users/me/calendarList",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        return JSONResponse([])
    items = resp.json().get("items", [])
    return JSONResponse([{"id": c["id"], "summary": c.get("summary", c["id"])} for c in items])
