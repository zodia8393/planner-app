"""VAPID Web Push helpers for planner apps.

Requires: pywebpush, cryptography
Free push notifications without FCM/APNs.
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL", "")


def get_vapid_public_key() -> str:
    return VAPID_PUBLIC_KEY


def save_subscription(conn, profile_id: int, subscription_json: str):
    """Save or update a push subscription for a profile."""
    try:
        endpoint = json.loads(subscription_json).get("endpoint", "")
    except (json.JSONDecodeError, TypeError):
        endpoint = ""
    conn.execute(
        "INSERT OR REPLACE INTO push_subscriptions (profile_id, endpoint, subscription_json, created_at) "
        "VALUES (?, ?, ?, datetime('now', 'localtime'))",
        (profile_id, endpoint, subscription_json),
    )


def remove_subscription(conn, profile_id: int, endpoint: str):
    """Remove a subscription by endpoint."""
    conn.execute(
        "DELETE FROM push_subscriptions WHERE profile_id=? AND endpoint=?",
        (profile_id, endpoint),
    )


def get_subscriptions(conn, profile_id: int) -> list[dict]:
    """Get all push subscriptions for a profile."""
    rows = conn.execute(
        "SELECT subscription_json FROM push_subscriptions WHERE profile_id=?",
        (profile_id,),
    ).fetchall()
    result = []
    for r in rows:
        try:
            result.append(json.loads(r["subscription_json"]))
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def send_push(conn, profile_id: int, title: str, body: str, url: str = "/", tag: str = ""):
    """Send push notification to all subscriptions of a profile."""
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("pywebpush not installed, skipping push")
        return

    subscriptions = get_subscriptions(conn, profile_id)
    if not subscriptions:
        return

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "tag": tag,
        "icon": "/static/icon-192.png",
    })

    vapid_claims = {"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"}

    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims,
            )
        except Exception as e:
            # Remove invalid subscriptions
            err_str = str(e)
            if "410" in err_str or "404" in err_str:
                endpoint = sub.get("endpoint", "")
                if endpoint:
                    remove_subscription(conn, profile_id, endpoint)
            logger.debug(f"Push failed: {e}")
