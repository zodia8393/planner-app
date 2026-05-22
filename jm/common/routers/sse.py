"""Common SSE, presence, and collaboration endpoints.

Shared across all planner apps (jm, my, work).
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()


# ── SSE Endpoint ──

@router.get("/events/stream")
async def sse_stream(request: Request):
    """Server-Sent Events for real-time updates.

    Broadcasts typed events: todo, event, memo, notice, presence.
    Uses the app's event_bus which supports typed events.
    """
    S = request.app.state
    bus = S.event_bus
    sid, queue = bus.subscribe()

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    if isinstance(msg, dict):
                        event_type = msg.get("type", "sync")
                        data = json.dumps(msg, ensure_ascii=False)
                        yield f"event: {event_type}\ndata: {data}\n\n"
                    else:
                        yield f"event: sync\ndata: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(sid)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Presence Tracking ──

@router.post("/api/presence")
async def report_presence(request: Request):
    """Report user presence on a specific page/entity.

    Body: {"page": "todos", "entity_id": 5}
    Stores in app.state.presence (in-memory dict, not DB).
    """
    S = request.app.state
    pid = S.get_profile_id(request)
    if not pid:
        return JSONResponse({"ok": False})

    body = await request.json()
    page = body.get("page", "")
    entity_id = body.get("entity_id")

    # Get profile name for display
    profile_name = S.get_profile_name(request)

    # Initialize presence store if not exists
    if not hasattr(S, "presence"):
        S.presence = {}

    now = time.time()
    S.presence[pid] = {
        "name": profile_name,
        "page": page,
        "entity_id": entity_id,
        "timestamp": now,
    }

    # Clean stale entries (>60s old)
    stale_cutoff = now - 60
    stale_keys = [k for k, v in S.presence.items() if v["timestamp"] < stale_cutoff]
    for k in stale_keys:
        del S.presence[k]

    # Broadcast presence update to SSE clients
    bus = S.event_bus
    active_users = [
        {"profile_id": k, "name": v["name"], "page": v["page"], "entity_id": v["entity_id"]}
        for k, v in S.presence.items()
        if v["timestamp"] >= stale_cutoff
    ]
    bus.emit("presence", {"users": active_users})

    return JSONResponse({"ok": True})


@router.get("/api/presence")
async def get_presence(request: Request):
    """Get current active users (presence info)."""
    S = request.app.state
    if not hasattr(S, "presence"):
        return JSONResponse({"users": []})

    now = time.time()
    stale_cutoff = now - 60
    active = [
        {"profile_id": k, "name": v["name"], "page": v["page"], "entity_id": v["entity_id"]}
        for k, v in S.presence.items()
        if v["timestamp"] >= stale_cutoff
    ]
    return JSONResponse({"users": active})


# ── GCal Sync Status ──

@router.get("/api/sync-status")
async def sync_status(request: Request):
    """Return Google Calendar sync status for current profile."""
    S = request.app.state
    pid = S.get_profile_id(request)
    if not pid:
        return JSONResponse({
            "gcal_connected": False,
            "last_sync": "",
            "pending_changes": 0,
            "conflicts": 0,
        })

    with S.get_db() as conn:
        # Check if gcal tokens exist (table may not exist yet)
        gcal_connected = False
        try:
            gcal_row = conn.execute(
                "SELECT token_expiry FROM gcal_tokens WHERE profile_id=?", (pid,)
            ).fetchone()
            gcal_connected = gcal_row is not None
        except Exception:
            pass

        # Count pending changes and conflicts
        pending = 0
        conflicts = 0
        last_sync = ""
        ev_cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
        if "gcal_sync_status" in ev_cols:
            pending_row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE profile_id=? AND gcal_sync_status='local_modified'",
                (pid,),
            ).fetchone()
            pending = pending_row[0] if pending_row else 0

            conflict_row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE profile_id=? AND gcal_sync_status='conflict'",
                (pid,),
            ).fetchone()
            conflicts = conflict_row[0] if conflict_row else 0

            last_sync_row = conn.execute(
                "SELECT MAX(gcal_last_synced) FROM events WHERE profile_id=? AND gcal_last_synced != ''",
                (pid,),
            ).fetchone()
            last_sync = last_sync_row[0] or "" if last_sync_row else ""

    return JSONResponse({
        "gcal_connected": gcal_connected,
        "last_sync": last_sync,
        "pending_changes": pending,
        "conflicts": conflicts,
    })
