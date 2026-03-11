"""
services/emotional_state.py — Infer the user's emotional state from their messages.

No biometrics needed. We read the tone of what the user sends to Genie and
infer their current state using Claude. This affects:
  - Whether to send the evening digest at all
  - The tone of every Genie response
  - Whether to pause proactive suggestions

Runs after every message batch and every 4 hours via scheduler.
"""
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
import database as db
from services.intelligence import _call_claude

logger = logging.getLogger(__name__)

# Emotional state hierarchy — higher index = more concern
STATE_LEVELS = {
    "happy": 0, "content": 0, "excited": 0,
    "neutral": 1,
    "tired": 2, "stressed": 2, "anxious": 2, "overwhelmed": 2,
    "sad": 3, "lonely": 3, "frustrated": 3,
    "grieving": 4, "distressed": 4,
    "crisis": 5,
}

PAUSE_PROACTIVE_ABOVE = 3   # grieving / distressed / crisis
SOFTEN_ABOVE = 2            # sad / lonely / frustrated / stressed


def infer_from_messages(user_id: str, recent_messages: list) -> Optional[dict]:
    """
    Analyze the tone of the user's recent messages to infer their emotional state.
    Called by the message batch processor after each batch.

    Only looks at messages sent BY the user (is_from_owner=True or body from Genie conversation).
    Saves result to emotional_states table.
    Returns the state dict or None if not enough signal.
    """
    # Filter to messages from the owner — we want the user's tone, not others'
    user_messages = [
        m for m in recent_messages
        if m.get("is_from_owner") or m.get("from_person_id") is None
    ]
    if len(user_messages) < 2:
        return None  # Not enough signal

    sample = "\n".join([
        f"[{m.get('timestamp', '')[:10]}] {m.get('body', '')}"
        for m in user_messages[-10:]  # last 10 user messages
    ])

    system_prompt = """You are an emotional intelligence reader for PersonalGenie.
Read these messages the user sent and infer their current emotional state.

Return JSON exactly:
{
  "inferred_mood": "one word from: happy / content / neutral / tired / stressed / anxious / sad / lonely / frustrated / grieving / distressed / crisis",
  "confidence": 0.0 to 1.0,
  "signals": ["specific signal from the text that led to this inference"],
  "intervention_threshold": "normal / gentle / pause / emergency",
  "recommended_action": "one plain English action Genie should take, or null"
}

intervention_threshold guide:
  normal — proceed with all suggestions as planned
  gentle — soften tone, reduce frequency by half
  pause — hold all proactive suggestions, respond only if user initiates
  emergency — crisis indicators present, surface support resources

Return only valid JSON. No explanation."""

    try:
        response = _call_claude(system_prompt, f"User messages:\n{sample}")
        if "```" in response:
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        state = json.loads(response.strip())

        # Save to emotional_states table
        supabase = db.get_db()
        supabase.table("emotional_states").insert({
            "id": str(uuid.uuid4()),
            "owner_user_id": user_id,
            "inferred_mood": state.get("inferred_mood", "neutral"),
            "confidence": state.get("confidence", 0.5),
            "signals": state.get("signals", []),
            "intervention_threshold": state.get("intervention_threshold", "normal"),
            "recommended_action": state.get("recommended_action"),
            "acted_on": False,
        }).execute()

        logger.info(
            f"Emotional state for user {user_id}: "
            f"{state.get('inferred_mood')} ({state.get('confidence', 0):.0%} confidence) "
            f"→ {state.get('intervention_threshold')}"
        )
        return state

    except Exception as e:
        logger.error(f"Emotional state inference failed for {user_id}: {e}")
        return None


def get_current_state(user_id: str) -> dict:
    """
    Return the most recent emotional state for a user.
    Falls back to neutral if no state has been inferred yet.
    """
    try:
        result = (
            db.get_db()
            .table("emotional_states")
            .select("*")
            .eq("owner_user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
    except Exception as e:
        logger.error(f"Could not load emotional state for {user_id}: {e}")

    return {
        "inferred_mood": "neutral",
        "confidence": 0.0,
        "intervention_threshold": "normal",
        "recommended_action": None,
    }


def should_send_digest(user_id: str) -> tuple:
    """
    Decide whether to send the evening digest based on current emotional state.
    Returns (should_send: bool, reason: str).
    """
    state = get_current_state(user_id)
    threshold = state.get("intervention_threshold", "normal")
    mood = state.get("inferred_mood", "neutral")

    if threshold == "emergency":
        return False, f"User in crisis state ({mood}) — digest paused"
    if threshold == "pause":
        return False, f"User in distress ({mood}) — digest paused"
    if threshold == "gentle":
        return True, f"User stressed ({mood}) — sending with softened tone"
    return True, "Normal"


def get_tone_modifier(user_id: str) -> str:
    """
    Return a tone instruction for Claude based on current emotional state.
    Injected into the conversation system prompt.
    """
    state = get_current_state(user_id)
    mood = state.get("inferred_mood", "neutral")
    threshold = state.get("intervention_threshold", "normal")

    if threshold == "emergency":
        return (
            "IMPORTANT: The user is showing signs of crisis. "
            "Be very gentle. Do not surface relationship suggestions. "
            "Ask how they are doing first. If appropriate, mention support resources."
        )
    if threshold == "pause":
        return (
            f"The user seems {mood} right now. Be warm and supportive. "
            "Listen more than you suggest. Do not push any relationship action items today."
        )
    if threshold == "gentle":
        return (
            f"The user seems {mood}. Keep suggestions light. "
            "Acknowledge their state before moving to relationship topics."
        )
    return ""  # Normal — no modifier needed
