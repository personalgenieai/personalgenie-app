"""
routers/push.py — Push notification management.

iOS registers its APNs device token here.
Backend uses it to send push notifications (moments, rule actions, etc.)
Auth: X-App-Token header (same pattern as all other routers).
"""
import json
import logging
import time
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import get_settings
from routers.auth import verify_app_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/push", tags=["push"])


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_user_id(request: Request) -> str:
    token = request.headers.get("X-App-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-App-Token")
    payload = verify_app_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]


# ── Pydantic models ───────────────────────────────────────────────────────────

class RegisterTokenRequest(BaseModel):
    user_id: str
    device_token: str
    platform: str = "ios"          # "ios" | "android"
    bundle_id: Optional[str] = None


class SendPushRequest(BaseModel):
    user_id: str
    title: str
    body: str
    data: Optional[dict] = None
    badge: Optional[int] = None


# ── APNs JWT helpers ──────────────────────────────────────────────────────────

def _make_apns_jwt(settings) -> Optional[str]:
    """
    Build a short-lived APNs JWT (ES256) from the .p8 key in settings.
    Returns None if any APNs setting is missing.
    """
    if not all([settings.apns_key_id, settings.apns_team_id, settings.apns_auth_key]):
        return None

    try:
        import base64
        import json as _json

        # jwt library from PyJWT; PyJWT supports ES256 natively
        import jwt as pyjwt

        # apns_auth_key may be base64-encoded or raw PEM
        raw_key = settings.apns_auth_key.strip()
        if not raw_key.startswith("-----"):
            # Assume base64-encoded
            raw_key = base64.b64decode(raw_key).decode("utf-8")

        now = int(time.time())
        token = pyjwt.encode(
            {"iss": settings.apns_team_id, "iat": now},
            raw_key,
            algorithm="ES256",
            headers={"kid": settings.apns_key_id},
        )
        return token if isinstance(token, str) else token.decode("utf-8")

    except Exception as exc:
        logger.error("Failed to create APNs JWT: %s", exc)
        return None


async def _send_apns(
    device_token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    badge: Optional[int] = None,
) -> str:
    """
    Send one APNs push notification.
    Returns "ok", "gone" (token invalid — deactivate), or "error:<msg>".
    """
    settings = get_settings()
    jwt_token = _make_apns_jwt(settings)
    if not jwt_token:
        logger.info("push not configured — would send: title=%r body=%r token=%s", title, body, device_token[-8:])
        return "not_configured"

    bundle_id = settings.apns_bundle_id
    if not bundle_id:
        logger.info("push not configured — apns_bundle_id missing")
        return "not_configured"

    host = (
        "https://api.sandbox.push.apple.com"
        if settings.apns_sandbox
        else "https://api.push.apple.com"
    )
    url = f"{host}/3/device/{device_token}"

    payload: dict = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
        }
    }
    if badge is not None:
        payload["aps"]["badge"] = badge
    if data:
        payload.update(data)

    headers = {
        "authorization": f"bearer {jwt_token}",
        "apns-push-type": "alert",
        "apns-topic": bundle_id,
        "apns-expiration": "0",
        "apns-priority": "10",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
            resp = await client.post(url, headers=headers, content=json.dumps(payload))
        if resp.status_code == 200:
            return "ok"
        if resp.status_code == 410:
            logger.info("APNs 410 Gone for token %s — deactivating", device_token[-8:])
            return "gone"
        logger.error("APNs error %s: %s", resp.status_code, resp.text[:200])
        return f"error:{resp.status_code}"
    except Exception as exc:
        logger.error("APNs request failed: %s", exc)
        return f"error:{exc}"


# ── Public helper (importable by rule_engine, nightly_conversations, etc.) ────

async def send_push_to_user(
    user_id: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    badge: Optional[int] = None,
) -> dict:
    """
    Send a push notification to all active tokens for a user.
    Returns {"sent": int, "failed": int, "skipped": int}.
    Automatically deactivates tokens that APNs reports as Gone (410).
    Can be imported and awaited by rule_engine.py and nightly_conversations.py.
    """
    from db import get_db
    supabase = get_db()

    result = (
        supabase.table("push_tokens")
        .select("id, device_token, platform")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .execute()
    )
    tokens = result.data or []

    if not tokens:
        logger.info("No active push tokens for user %s", user_id)
        return {"sent": 0, "failed": 0, "skipped": 0}

    sent = failed = skipped = 0
    for tok in tokens:
        platform = tok.get("platform", "ios")
        device_token = tok["device_token"]

        if platform == "ios":
            outcome = await _send_apns(device_token, title, body, data, badge)
            if outcome == "ok":
                sent += 1
                supabase.table("push_tokens").update(
                    {"last_used_at": "now()"}
                ).eq("id", tok["id"]).execute()
            elif outcome == "gone":
                supabase.table("push_tokens").update(
                    {"is_active": False}
                ).eq("id", tok["id"]).execute()
                failed += 1
            elif outcome == "not_configured":
                skipped += 1
            else:
                failed += 1
        else:
            # Android / FCM — not yet implemented
            logger.info("FCM push not yet implemented — skipping token for user %s", user_id)
            skipped += 1

    return {"sent": sent, "failed": failed, "skipped": skipped}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register")
async def register_token(request: Request, body: RegisterTokenRequest):
    """
    iOS (or Android) app registers its device token after APNs grants one.
    Upserts into push_tokens — safe to call on every app launch.
    """
    _get_user_id(request)  # auth check

    if body.platform not in ("ios", "android"):
        raise HTTPException(status_code=400, detail="platform must be 'ios' or 'android'")
    if not body.device_token.strip():
        raise HTTPException(status_code=400, detail="device_token is required")

    try:
        from db import get_db
        supabase = get_db()
        supabase.table("push_tokens").upsert(
            {
                "user_id": body.user_id,
                "device_token": body.device_token.strip(),
                "platform": body.platform,
                "bundle_id": body.bundle_id,
                "is_active": True,
                "registered_at": "now()",
            },
            on_conflict="user_id,device_token",
        ).execute()
    except Exception as exc:
        logger.error("Failed to register push token for user %s: %s", body.user_id, exc)
        raise HTTPException(status_code=500, detail="Could not register token")

    return {"status": "registered"}


@router.delete("/token/{user_id}")
async def deactivate_token(user_id: str, request: Request):
    """
    Soft-delete all active tokens for a user when they sign out.
    Sets is_active = False rather than deleting so we keep the history.
    """
    _get_user_id(request)  # auth check

    try:
        from db import get_db
        supabase = get_db()
        supabase.table("push_tokens").update({"is_active": False}).eq("user_id", user_id).execute()
    except Exception as exc:
        logger.error("Failed to deactivate tokens for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Could not deactivate token")

    return {"status": "deactivated"}


@router.post("/send")
async def send_push(request: Request, body: SendPushRequest):
    """
    Internal endpoint: send a push notification to a user by user_id.
    Used by the rule engine, nightly conversations, and other services.
    Not exposed to untrusted callers — still requires a valid X-App-Token.
    """
    _get_user_id(request)  # auth check

    result = await send_push_to_user(
        user_id=body.user_id,
        title=body.title,
        body=body.body,
        data=body.data,
        badge=body.badge,
    )
    return result


@router.get("/tokens/{user_id}")
async def list_tokens(user_id: str, request: Request):
    """List all active push tokens for a user (for debugging / admin)."""
    _get_user_id(request)  # auth check

    try:
        from db import get_db
        supabase = get_db()
        result = (
            supabase.table("push_tokens")
            .select("id, platform, bundle_id, is_active, registered_at, last_used_at")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .order("registered_at", desc=True)
            .execute()
        )
        return {"tokens": result.data or []}
    except Exception as exc:
        logger.error("Failed to list tokens for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Could not list tokens")
