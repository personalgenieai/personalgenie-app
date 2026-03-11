"""
routers/health.py — Health Genie endpoints.

Two flows for the POC:

1. Food log — user sends any food description (text or voice transcript) and
   Genie parses, stores, and optionally acknowledges it.

2. Training session — user signals "starting session", Genie replies and sets
   a waiting state. User then sends a voice note; Genie transcribes and stores
   the session. (Training session logic built in Sprint 2.)

These endpoints are also called internally from the WhatsApp message router
when food or session intent is detected in an incoming message.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import database as db
from services.nutrition import (
    parse_food_input,
    store_food_log,
    get_daily_summary,
    get_days_logging,
    build_acknowledgment,
)
from services.whatsapp import send_message
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/health", tags=["health"])


# ── Request models ────────────────────────────────────────────────────────────

class FoodLogRequest(BaseModel):
    user_id: str
    raw_input: str
    input_type: str = "text"           # text | voice
    user_tz_offset: int = 0            # hours from UTC — used for date assignment


class SessionStartRequest(BaseModel):
    user_id: str
    phone: str                         # to send the "I'm listening" reply


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/food-log")
async def log_food(req: FoodLogRequest):
    """
    Parse and store a food log entry.

    Called either directly from the iOS app or internally when the WhatsApp
    message router detects food intent in an incoming message.

    Returns the acknowledgment string (or None if below significance threshold).
    """
    user = db.get_user_by_id(req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    parsed = parse_food_input(req.raw_input, req.input_type)
    daily = store_food_log(req.user_id, req.raw_input, parsed, req.input_type, req.user_tz_offset)
    days = get_days_logging(req.user_id)
    ack = build_acknowledgment(parsed, daily, days)

    return {
        "status": "logged",
        "total_calories": parsed.get("total_calories", 0),
        "total_protein": parsed.get("total_protein", 0),
        "overall_confidence": parsed.get("overall_confidence", 1.0),
        "clarification_question": parsed.get("clarification_question"),
        "acknowledgment": ack,
        "logged_silently": ack is None,
    }


@router.post("/session-start")
async def start_training_session(req: SessionStartRequest):
    """
    Handle 'starting session' trigger. Sends a reply via WhatsApp and marks
    the user as awaiting a session voice note.

    The actual session voice note processing is Sprint 2 (TrainingSessionService).
    This endpoint just acknowledges and sets the waiting state in memory.
    """
    user = db.get_user_by_id(req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Import here to avoid circular dependency — session state lives in messages router
    from routers.messages import set_health_session_active
    set_health_session_active(req.user_id, True)

    reply = "I'm listening. Send me a voice note when you're done and I'll put together a summary."
    send_message(req.phone, reply, user_id=req.user_id)

    return {"status": "session_started", "user_id": req.user_id}


@router.get("/summary/{user_id}")
async def get_health_summary(user_id: str):
    """
    Return today's health summary for a user.
    Used by the iOS dashboard and internal checks.
    """
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    daily = get_daily_summary(user_id)
    days = get_days_logging(user_id)

    return {
        "today": daily,
        "days_logging": days,
        "habit_established": days >= 7,
    }
