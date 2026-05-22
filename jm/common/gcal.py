"""Google Calendar OAuth2 integration for planner apps.

All functions accept explicit parameters (access tokens, calendar IDs,
db connections) rather than reading module-level globals or calling get_db().
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import httpx

__all__ = [
    "GCAL_CLIENT_ID",
    "GCAL_CLIENT_SECRET",
    "GCAL_SCOPES",
    "GCAL_AUTH_URL",
    "GCAL_TOKEN_URL",
    "GCAL_API_BASE",
    "gcal_redirect_uri",
    "gcal_refresh_token",
    "gcal_fetch_events",
    "gcal_push_event",
    "gcal_update_event",
    "gcal_delete_event",
]

# ── Constants (read from env) ──
GCAL_CLIENT_ID = os.environ.get("GCAL_CLIENT_ID", "")
GCAL_CLIENT_SECRET = os.environ.get("GCAL_CLIENT_SECRET", "")
GCAL_SCOPES = "https://www.googleapis.com/auth/calendar"
GCAL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GCAL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GCAL_API_BASE = "https://www.googleapis.com/calendar/v3"


def gcal_redirect_uri(request) -> str:
    """Build the OAuth2 redirect URI from the incoming request."""
    host = request.headers.get("host", "localhost:8002")
    scheme = request.headers.get(
        "x-forwarded-proto",
        request.headers.get("x-forwarded-scheme", request.url.scheme),
    )
    if "fly.dev" in host:
        scheme = "https"
    return f"{scheme}://{host}/settings/gcal/callback"


async def gcal_refresh_token(conn, profile_id: int) -> Optional[str]:
    """Return a valid access token for *profile_id*, refreshing if needed.

    Args:
        conn: A sqlite3 connection (must have row_factory set).
        profile_id: The profile to look up in ``gcal_tokens``.

    Returns:
        A valid access token string, or ``None`` if unavailable.
    """
    row = conn.execute(
        "SELECT * FROM gcal_tokens WHERE profile_id=?", (profile_id,)
    ).fetchone()
    if not row:
        return None
    expiry = datetime.fromisoformat(row["token_expiry"])
    if datetime.now() < expiry - timedelta(minutes=2):
        return row["access_token"]
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GCAL_TOKEN_URL,
            data={
                "client_id": GCAL_CLIENT_ID,
                "client_secret": GCAL_CLIENT_SECRET,
                "refresh_token": row["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code != 200:
        return None
    data = resp.json()
    new_expiry = (
        datetime.now() + timedelta(seconds=data["expires_in"])
    ).isoformat()
    conn.execute(
        "UPDATE gcal_tokens SET access_token=?, token_expiry=? WHERE profile_id=?",
        (data["access_token"], new_expiry, profile_id),
    )
    return data["access_token"]


async def gcal_fetch_events(
    access_token: str, calendar_id: str, time_min: str, time_max: str
) -> list:
    """Fetch events from Google Calendar via HTTP.

    Args:
        access_token: A valid OAuth2 bearer token.
        calendar_id: Calendar ID (e.g. ``"primary"``).
        time_min: Start date as ``YYYY-MM-DD``.
        time_max: End date as ``YYYY-MM-DD``.

    Returns:
        A list of event dicts with keys: id, title, start_time, end_time,
        color, is_gcal, location.
    """
    params = {
        "timeMin": f"{time_min}T00:00:00+09:00",
        "timeMax": f"{time_max}T23:59:59+09:00",
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "200",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GCAL_API_BASE}/calendars/{calendar_id}/events",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        return []
    items = resp.json().get("items", [])
    events = []
    for item in items:
        start = item.get("start", {})
        end = item.get("end", {})
        start_dt = start.get("dateTime", start.get("date", ""))
        end_dt = end.get("dateTime", end.get("date", ""))
        events.append({
            "id": item["id"],
            "title": item.get("summary", "(제목 없음)"),
            "start_time": start_dt,
            "end_time": end_dt,
            "color": "#4285f4",
            "is_gcal": True,
            "location": item.get("location", ""),
        })
    return events


def _build_event_body(
    title: str, start_time: str, end_time: str = ""
) -> dict:
    """Build a Google Calendar event body from title and time strings."""
    body: dict = {"summary": title}
    if "T" in start_time:
        body["start"] = {
            "dateTime": (
                start_time + ":00+09:00"
                if len(start_time) == 16
                else start_time
            ),
            "timeZone": "Asia/Seoul",
        }
        if end_time and "T" in end_time:
            body["end"] = {
                "dateTime": (
                    end_time + ":00+09:00"
                    if len(end_time) == 16
                    else end_time
                ),
                "timeZone": "Asia/Seoul",
            }
        else:
            body["end"] = body["start"]
    else:
        body["start"] = {"date": start_time[:10]}
        body["end"] = {"date": (end_time[:10] if end_time else start_time[:10])}
    return body


async def gcal_push_event(
    access_token: str,
    calendar_id: str,
    title: str,
    start_time: str,
    end_time: str = "",
) -> str:
    """Create an event in Google Calendar.

    Returns:
        The new event's Google Calendar ID, or ``""`` on failure.
    """
    body = _build_event_body(title, start_time, end_time)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GCAL_API_BASE}/calendars/{calendar_id}/events",
            json=body,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code in (200, 201):
        return resp.json().get("id", "")
    return ""


async def gcal_update_event(
    access_token: str,
    calendar_id: str,
    event_id: str,
    title: str,
    start_time: str,
    end_time: str = "",
) -> None:
    """Update an existing event in Google Calendar."""
    if not event_id:
        return
    body = _build_event_body(title, start_time, end_time)
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{GCAL_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            json=body,
            headers={"Authorization": f"Bearer {access_token}"},
        )


async def gcal_delete_event(
    access_token: str, calendar_id: str, event_id: str
) -> None:
    """Delete an event from Google Calendar."""
    if not event_id:
        return
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{GCAL_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
