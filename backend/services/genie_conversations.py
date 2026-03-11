"""
services/genie_conversations.py — Proactive Genie-initiated conversations.

Rather than waiting for the user to ask questions, Genie occasionally opens
a conversation to learn more about a relationship — filling in gaps in the
People Graph through natural dialogue.

Triggered by:
  - Drift detection (what happened with this person?)
  - Approaching birthday (what would they actually want?)
  - Low memory count on a high-closeness person
  - User mentions someone Genie doesn't know well

Each conversation has a single purpose. Genie asks one question, listens,
extracts the insight, and updates the person's profile. Never interrogates.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
import database as db
from services.intelligence import _call_claude
from services.whatsapp import send_message

logger = logging.getLogger(__name__)

# How many days between proactive conversations per person
MIN_DAYS_BETWEEN_CONVERSATIONS = 14

CONVERSATION_TYPES = {
    "drift_check": "understand what's happening in a quieted relationship",
    "birthday_prep": "learn what would make a birthday acknowledgement feel personal",
    "memory_update": "fill a gap in the relationship profile",
    "relationship_check": "get a sense of how a relationship is evolving",
}


def should_initiate(user_id: str, person_id: str) -> bool:
    """
    Check whether enough time has passed since the last Genie conversation
    with this person before starting a new one.
    """
    try:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=MIN_DAYS_BETWEEN_CONVERSATIONS)).isoformat()
        result = (
            db.get_db()
            .table("genie_conversations")
            .select("id")
            .eq("owner_user_id", user_id)
            .eq("person_id", person_id)
            .gte("created_at", cutoff)
            .execute()
        )
        return not result.data
    except Exception:
        return True


def start_conversation(
    user_id: str,
    person_id: str,
    conversation_type: str,
    phone: str,
) -> Optional[str]:
    """
    Initiate a proactive Genie conversation about a specific person.
    Sends a WhatsApp message and saves the conversation record.

    Returns the conversation_id if started, None if skipped.
    """
    if conversation_type not in CONVERSATION_TYPES:
        logger.warning(f"Unknown conversation type: {conversation_type}")
        return None

    if not should_initiate(user_id, person_id):
        logger.info(f"Too soon for another conversation about person {person_id}")
        return None

    person = db.get_person_by_id(person_id)
    if not person:
        return None

    person_name = person.get("name", "them")
    memories = person.get("memories", [])
    relationship_type = person.get("relationship_type", "")
    closeness = person.get("closeness_score", 0.5)

    # Generate the opening question using Claude
    system_prompt = f"""You are Personal Genie opening a short conversation to learn more about
{person_name} ({relationship_type}) in {_get_user_name(user_id)}'s life.

Purpose: {CONVERSATION_TYPES[conversation_type]}

What you already know:
- Closeness score: {closeness:.1f}
- Memories: {json.dumps(memories[:3])}

Write ONE warm, specific opening question. Rules:
- Never explain why you're asking. Just ask naturally.
- Reference something specific you know if possible.
- Short — one sentence maximum.
- Warm and curious, not clinical.
- Do not start with "Hey" or "Hi".
- Never say "I noticed" or "based on your data"."""

    try:
        opening = _call_claude(system_prompt, f"Conversation type: {conversation_type}")
        opening = opening.strip().strip('"')
    except Exception as e:
        logger.error(f"Could not generate conversation opening: {e}")
        return None

    # Save the conversation record
    conversation_id = str(uuid.uuid4())
    try:
        db.get_db().table("genie_conversations").insert({
            "id": conversation_id,
            "owner_user_id": user_id,
            "person_id": person_id,
            "conversation_type": conversation_type,
            "genie_opening": opening,
            "exchanges": [],
            "user_engaged": False,
        }).execute()
    except Exception as e:
        logger.error(f"Could not save genie conversation: {e}")
        return None

    # Send the message
    try:
        send_message(phone, opening)
        logger.info(f"Started {conversation_type} conversation about {person_name} with user {user_id}")
        return conversation_id
    except Exception as e:
        logger.error(f"Could not send conversation opening: {e}")
        return None


def continue_conversation(
    user_id: str,
    user_reply: str,
    phone: str,
) -> Optional[str]:
    """
    Continue the most recent active Genie conversation.
    Extracts insights from the user's reply, updates the person's profile,
    and either asks a follow-up or closes the conversation gracefully.

    Returns the insight extracted, or None if no active conversation.
    """
    # Find the most recent conversation that hasn't been completed
    try:
        result = (
            db.get_db()
            .table("genie_conversations")
            .select("*")
            .eq("owner_user_id", user_id)
            .is_("insight_extracted", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        conversation = result.data[0]
    except Exception:
        return None

    conversation_id = conversation["id"]
    person_id = conversation["person_id"]
    person = db.get_person_by_id(person_id)
    if not person:
        return None

    person_name = person.get("name", "them")
    opening = conversation.get("genie_opening", "")
    exchanges = conversation.get("exchanges") or []

    # Add user reply to exchanges
    exchanges.append({"role": "user", "content": user_reply})

    # Ask Claude to extract insight and decide whether to follow up
    system_prompt = f"""You are Personal Genie, continuing a conversation about {person_name}.

Opening question you asked: "{opening}"
User replied: "{user_reply}"

Do two things:
1. Extract any useful relationship insight from the reply.
2. Decide whether to ask one follow-up question or close gracefully.

Return JSON:
{{
  "insight": "specific fact worth saving to the relationship profile, or null",
  "profile_field": "which field this updates: memories / topics / communication_style / relationship_health_score / null",
  "profile_value": "the value to store, or null",
  "follow_up": "one warm follow-up question if you need more, or null to close",
  "closing_message": "warm closing line if follow_up is null, or null"
}}

Return only valid JSON."""

    try:
        response = _call_claude(system_prompt, f"Reply: {user_reply}")
        if "```" in response:
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        extracted = json.loads(response.strip())
    except Exception as e:
        logger.error(f"Could not process conversation reply: {e}")
        return None

    insight = extracted.get("insight")
    follow_up = extracted.get("follow_up")
    closing = extracted.get("closing_message")
    profile_field = extracted.get("profile_field")
    profile_value = extracted.get("profile_value")

    # Update person profile if we got something useful
    if insight and profile_field and profile_value:
        try:
            if profile_field == "memories":
                existing = person.get("memories", []) or []
                db.upsert_person(user_id, {
                    "name": person_name,
                    "memories": existing + [{"description": insight, "source": "genie_conversation"}],
                })
            elif profile_field == "topics":
                existing = person.get("topics", []) or []
                topics = profile_value if isinstance(profile_value, list) else [profile_value]
                db.upsert_person(user_id, {
                    "name": person_name,
                    "topics": list(set(existing + topics)),
                })
            elif profile_field == "communication_style":
                db.upsert_person(user_id, {
                    "name": person_name,
                    "communication_style": str(profile_value),
                })
        except Exception as e:
            logger.error(f"Could not update person profile from conversation: {e}")

    # Add Genie's response to exchanges
    genie_reply = follow_up or closing or ""
    if genie_reply:
        exchanges.append({"role": "assistant", "content": genie_reply})

    # Update the conversation record
    try:
        update = {
            "exchanges": exchanges,
            "user_engaged": True,
        }
        if not follow_up:
            # Conversation is complete
            update["insight_extracted"] = insight or "User engaged"
            update["profile_field_updated"] = profile_field
            update["profile_update_value"] = profile_value

        db.get_db().table("genie_conversations").update(update).eq("id", conversation_id).execute()
    except Exception as e:
        logger.error(f"Could not update genie conversation: {e}")

    # Send reply
    if genie_reply:
        try:
            send_message(phone, genie_reply)
        except Exception as e:
            logger.error(f"Could not send conversation reply: {e}")

    return insight


def get_active_conversation(user_id: str) -> Optional[dict]:
    """
    Return the most recent incomplete Genie-initiated conversation for a user.
    Used by the consent router to check if an incoming message is a conversation reply.
    """
    try:
        result = (
            db.get_db()
            .table("genie_conversations")
            .select("*")
            .eq("owner_user_id", user_id)
            .is_("insight_extracted", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def _get_user_name(user_id: str) -> str:
    user = db.get_user_by_id(user_id)
    return user.get("name", "the user") if user else "the user"
