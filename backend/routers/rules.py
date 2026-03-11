"""
routers/rules.py — Genie Rule Engine endpoints.

Endpoints:
  GET  /rules/{user_id}   — list active rules
  POST /rules             — create rule from natural language
  DELETE /rules/{rule_id} — delete a rule

Rules are defined in natural language. Claude parses them into
structured trigger/action objects. Always confirms in plain English
before activating (the iOS app shows a preview step).

Trigger types: time, incoming_message, calendar_event, transaction,
               music_playing, health_metric, genie_observation
Action types:  send_whatsapp, play_music, send_reminder, log_data,
               notify_ios, speak_on_speaker, start_conversation
"""
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import get_settings
from routers.auth import verify_app_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rules", tags=["rules"])


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

class CreateRuleRequest(BaseModel):
    user_id: str
    natural_language: str


class DeleteRuleRequest(BaseModel):
    user_id: str


# ── Rule parser ───────────────────────────────────────────────────────────────

TRIGGER_TYPES = [
    "time", "incoming_message", "calendar_event", "calendar_free",
    "transaction", "music_playing", "health_metric", "genie_observation", "rule_fired",
]

ACTION_TYPES = [
    "send_whatsapp", "claude_analysis", "device_command", "play_music",
    "start_conversation", "log_data", "send_reminder", "update_world_model",
    "notify_ios", "speak_on_speaker",
]


async def _parse_rule_with_claude(natural_language: str) -> dict:
    """
    Ask Claude to parse a natural-language rule into a structured object.
    Returns a dict with: plain_english, trigger_type, trigger_config,
    action_type, action_config.
    """
    settings = get_settings()
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    trigger_list = ", ".join(TRIGGER_TYPES)
    action_list  = ", ".join(ACTION_TYPES)

    prompt = f"""Parse this Genie rule from natural language into structured JSON.

Rule: "{natural_language}"

Available trigger types: {trigger_list}
Available action types: {action_list}

Return ONLY this JSON structure, nothing else:
{{
  "plain_english": "A clear 1-sentence description of what this rule does",
  "trigger_type": "one of the trigger types above",
  "trigger_config": {{ relevant config for this trigger }},
  "action_type": "one of the action types above",
  "action_config": {{ relevant config for this action }}
}}

Examples:
- "Remind me if I haven't logged food by 8pm" →
  trigger_type: "time", trigger_config: {{"hour": 20, "condition": "no_food_logged_today"}},
  action_type: "notify_ios", action_config: {{"message": "Haven't heard what you ate today."}}

- "Play my wind-down playlist at 10pm on weekdays" →
  trigger_type: "time", trigger_config: {{"hour": 22, "days": ["mon","tue","wed","thu","fri"]}},
  action_type: "play_music", action_config: {{"query": "wind-down playlist"}}

- "If I haven't talked to Alice in 2 weeks, let me know" →
  trigger_type: "genie_observation", trigger_config: {{"person_name": "Alice", "silence_days": 14}},
  action_type: "notify_ios", action_config: {{"message": "It's been 2 weeks since you connected with Alice."}}
"""

    msg = client.messages.create(
        model=settings.claude_model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()

    import re
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"Could not parse Claude's rule output: {raw[:100]}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{user_id}")
async def list_rules(user_id: str, request: Request):
    _get_user_id(request)  # auth check
    try:
        from db import get_db
        db = get_db()
        result = (
            db.table("genie_rules")
            .select("*")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
        )
        return {"rules": result.data or []}
    except Exception as exc:
        logger.error("Failed to list rules for %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Could not load rules")


@router.post("")
async def create_rule(request: Request, body: CreateRuleRequest):
    _get_user_id(request)

    if not body.natural_language.strip():
        raise HTTPException(status_code=400, detail="natural_language is required")

    try:
        parsed = await _parse_rule_with_claude(body.natural_language.strip())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not understand rule: {exc}")

    rule_id = str(uuid.uuid4())
    rule_row = {
        "id": rule_id,
        "user_id": body.user_id,
        "plain_english": parsed.get("plain_english", body.natural_language),
        "trigger_type": parsed.get("trigger_type", "genie_observation"),
        "action_type": parsed.get("action_type", "notify_ios"),
        "trigger_config": json.dumps(parsed.get("trigger_config", {})),
        "action_config": json.dumps(parsed.get("action_config", {})),
        "is_active": True,
    }

    try:
        from db import get_db
        db = get_db()
        db.table("genie_rules").insert(rule_row).execute()
    except Exception as exc:
        logger.error("Failed to save rule: %s", exc)
        raise HTTPException(status_code=500, detail="Could not save rule")

    return {
        **rule_row,
        "trigger_config": parsed.get("trigger_config", {}),
        "action_config": parsed.get("action_config", {}),
    }


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str, request: Request, body: DeleteRuleRequest):
    _get_user_id(request)
    try:
        from db import get_db
        db = get_db()
        db.table("genie_rules").update({"is_active": False}).eq("id", rule_id).eq("user_id", body.user_id).execute()
    except Exception as exc:
        logger.error("Failed to delete rule %s: %s", rule_id, exc)
        raise HTTPException(status_code=500, detail="Could not delete rule")
    return {"status": "deleted"}
