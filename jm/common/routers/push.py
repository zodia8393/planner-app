"""Push notifications router — /api/push/*."""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from common.webpush import get_vapid_public_key, save_subscription, remove_subscription, send_push

router = APIRouter()


@router.get("/api/push/vapid-key", response_class=JSONResponse)
async def api_vapid_key():
    return JSONResponse({"publicKey": get_vapid_public_key()})


@router.post("/api/push/subscribe", response_class=JSONResponse)
async def api_push_subscribe(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    body = await request.json()
    sub_json = json.dumps(body.get("subscription", body))
    with S.get_db() as conn:
        save_subscription(conn, pid, sub_json)
    return JSONResponse({"ok": True})


@router.post("/api/push/unsubscribe", response_class=JSONResponse)
async def api_push_unsubscribe(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    body = await request.json()
    endpoint = body.get("endpoint", "")
    with S.get_db() as conn:
        remove_subscription(conn, pid, endpoint)
    return JSONResponse({"ok": True})


@router.post("/api/push/test", response_class=JSONResponse)
async def api_push_test(request: Request):
    """Send a test push notification."""
    S = request.app.state
    pid = S.get_profile_id(request)
    app_name = getattr(S, "app_display_name", "Planner")
    with S.get_db() as conn:
        send_push(conn, pid, app_name, "푸시 알림이 정상 동작합니다!", "/")
    return JSONResponse({"ok": True})
