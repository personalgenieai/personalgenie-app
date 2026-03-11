"""
routers/permissions.py — Cross-user permission grants.

Endpoints:
  POST /permissions/grant          — grant permission to use your signals to help someone
  POST /permissions/revoke         — instantly revoke a permission grant
  GET  /permissions/outbound       — list permissions you have granted
  GET  /permissions/signal-counts  — how many signals you've contributed (Settings → Privacy)
"""
import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routers.auth import verify_app_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/permissions", tags=["permissions"])


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_user_id(request: Request) -> str:
    token = request.headers.get("X-App-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-App-Token")
    payload = verify_app_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]


def _hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.strip().encode()).hexdigest()


# ── Pydantic models ───────────────────────────────────────────────────────────

class GrantRequest(BaseModel):
    beneficiary_phone: str    # the person you want Genie to help (their phone number)
    permission_level: int = 1  # 0=silent 1=passive 2=soft_bridge 3=named
    scope: str = "wellbeing"   # wellbeing | factual | all
    note: str = ""             # optional: why ("I want Genie to look out for TJ")


class RevokeRequest(BaseModel):
    beneficiary_phone: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/grant")
async def grant_permission(request: Request, body: GrantRequest):
    """
    Grant Genie permission to use your relationship signals to help someone.

    Levels:
      0 = silent (default — Genie already does this, this makes it explicit)
      1 = passive bridge (Genie can be more attentive with them, no attribution)
      2 = soft bridge (they know someone close is thinking of them, no name)
      3 = named bridge (they know it's you — both must opt in)
    """
    user_id = _get_user_id(request)

    if body.permission_level not in (0, 1, 2, 3):
        raise HTTPException(status_code=400, detail="permission_level must be 0, 1, 2, or 3")

    if body.scope not in ("wellbeing", "factual", "all"):
        raise HTTPException(status_code=400, detail="scope must be wellbeing, factual, or all")

    phone_hash = _hash_phone(body.beneficiary_phone)

    try:
        from db import get_db
        db = get_db()

        # Check if beneficiary is already a Genie user
        user_result = (
            db.table("users")
            .select("id")
            .eq("phone", body.beneficiary_phone)
            .execute()
        )
        beneficiary_user_id = user_result.data[0]["id"] if user_result.data else None

        # Upsert (replace any existing grant for this pair)
        db.table("cross_user_permissions").upsert({
            "granting_user_id": user_id,
            "beneficiary_phone_hash": phone_hash,
            "beneficiary_user_id": beneficiary_user_id,
            "permission_level": body.permission_level,
            "scope": body.scope,
            "granting_note": body.note or None,
            "revoked_at": None,
        }).execute()

        # If beneficiary is a user, mark their World Model stale
        if beneficiary_user_id:
            db.table("world_model").update({"is_stale": True}).eq("user_id", beneficiary_user_id).execute()

    except Exception as exc:
        logger.error("Failed to grant permission: %s", exc)
        raise HTTPException(status_code=500, detail="Could not save permission")

    level_descriptions = {
        0: "Genie will silently use your insights to care for them",
        1: "Genie will be more attentive to them — no attribution",
        2: "They'll know someone close is thinking of them — no name shared",
        3: "They'll know it's you — they must also opt in",
    }
    return {
        "status": "granted",
        "level": body.permission_level,
        "description": level_descriptions[body.permission_level],
    }


@router.post("/revoke")
async def revoke_permission(request: Request, body: RevokeRequest):
    """Instantly revoke a previously granted permission."""
    user_id = _get_user_id(request)
    phone_hash = _hash_phone(body.beneficiary_phone)

    try:
        from db import get_db
        from datetime import datetime, timezone
        db = get_db()

        db.table("cross_user_permissions").update({
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        }).eq("granting_user_id", user_id).eq("beneficiary_phone_hash", phone_hash).execute()

    except Exception as exc:
        logger.error("Failed to revoke permission: %s", exc)
        raise HTTPException(status_code=500, detail="Could not revoke permission")

    return {"status": "revoked"}


@router.get("/outbound")
async def list_outbound_permissions(request: Request):
    """
    List all active permission grants this user has made.
    Used in Settings → Privacy → "People you're watching out for".
    Phone numbers are NOT returned — only level, scope, and when granted.
    """
    user_id = _get_user_id(request)

    try:
        from db import get_db
        db = get_db()

        result = (
            db.table("cross_user_permissions")
            .select("permission_level, scope, granted_at, granting_note, revoked_at")
            .eq("granting_user_id", user_id)
            .is_("revoked_at", "null")
            .execute()
        )

        level_labels = {0: "Silent care", 1: "Attentive care", 2: "Soft bridge", 3: "Named bridge"}
        return {
            "grants": [
                {
                    "level": r["permission_level"],
                    "level_label": level_labels.get(r["permission_level"], "Unknown"),
                    "scope": r["scope"],
                    "granted_at": r["granted_at"],
                    "note": r.get("granting_note"),
                }
                for r in (result.data or [])
            ]
        }
    except Exception as exc:
        logger.error("Failed to list permissions: %s", exc)
        raise HTTPException(status_code=500, detail="Could not load permissions")


@router.get("/signal-counts")
async def signal_counts(request: Request):
    """
    Return how many third-party signals this user has contributed.
    Used in Settings → Privacy → "What Genie skips" / "What you've shared".
    Shows counts only — never content, never names.
    """
    user_id = _get_user_id(request)

    try:
        from db import get_db
        db = get_db()

        result = (
            db.table("third_party_signals")
            .select("signal_type")
            .eq("source_user_id", user_id)
            .execute()
        )

        counts: dict[str, int] = {}
        for row in (result.data or []):
            t = row["signal_type"]
            counts[t] = counts.get(t, 0) + 1

        return {
            "total_signals_contributed": sum(counts.values()),
            "by_type": counts,
        }
    except Exception as exc:
        logger.error("Failed to get signal counts: %s", exc)
        raise HTTPException(status_code=500, detail="Could not load signal counts")
