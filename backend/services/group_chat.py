"""
services/group_chat.py — Analyse WhatsApp group chat dynamics.

Group chats reveal a different layer of relationships — who you address
directly, what topics only come up in groups, subrelationships you don't
have 1:1. This module builds profiles for each group.

Called by the message batch processor whenever group messages are present.
"""
import json
import logging
import uuid
from collections import defaultdict
from typing import Optional
import database as db
from services.intelligence import _call_claude

logger = logging.getLogger(__name__)


def analyze_group_messages(user_id: str, messages: list) -> int:
    """
    Identify group messages, group them by group_id, build or update
    a group_chat_profile for each one.

    Returns the number of profiles created or updated.
    """
    # Separate group messages (have a group_id) from 1:1 messages
    groups: dict = defaultdict(list)
    for msg in messages:
        group_id = msg.get("group_id")
        if group_id:
            groups[group_id].append(msg)

    if not groups:
        return 0

    updated = 0
    supabase = db.get_db()

    for group_id, group_msgs in groups.items():
        try:
            profile = _build_group_profile(user_id, group_id, group_msgs, supabase)
            if profile:
                updated += 1
        except Exception as e:
            logger.error(f"Group chat analysis failed for group {group_id}: {e}")

    logger.info(f"Group chat analysis: updated {updated} profiles for user {user_id}")
    return updated


def _build_group_profile(user_id: str, group_id: str, messages: list, supabase) -> Optional[dict]:
    """
    Analyse one group's messages and upsert a group_chat_profile record.
    """
    if len(messages) < 3:
        return None  # Not enough signal

    # Format for Claude
    messages_text = "\n".join([
        f"[{m.get('timestamp', '')[:10]}] "
        f"{'(me)' if m.get('is_from_owner') else m.get('people', {}).get('name', 'Unknown')}: "
        f"{m.get('body', '')}"
        for m in messages[-50:]  # last 50 messages from this group
    ])

    # Extract unique member phones
    member_phones = list({
        m.get("people", {}).get("phone", "")
        for m in messages
        if m.get("people", {}).get("phone")
    })

    owner_messages = [m for m in messages if m.get("is_from_owner")]
    owner_ratio = len(owner_messages) / len(messages) if messages else 0

    system_prompt = """Analyse this WhatsApp group chat and return a JSON profile.

Return exactly:
{
  "group_name": "inferred name or null",
  "owner_role": "organiser / participant / lurker / connector",
  "recurring_topics": ["topic1", "topic2"],
  "topics_only_in_group": ["topic that never comes up 1:1"],
  "direct_address_patterns": {"person_name": "how owner addresses them in group"},
  "subrelationship_signals": [
    {"person_a": "name", "person_b": "name", "signal": "what their dynamic looks like"}
  ],
  "group_health_score": 0.0 to 1.0,
  "key_insight": "one observation about this group that would surprise the owner"
}

Rules:
- Be specific. Reference actual words from the messages.
- direct_address_patterns: note if owner uses nicknames, formal names, or terms of endearment.
- subrelationship_signals: only include clear signals, not guesses.
- Return only valid JSON."""

    try:
        response = _call_claude(system_prompt, f"Group chat ({len(messages)} messages):\n{messages_text}")
        if "```" in response:
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        profile_data = json.loads(response.strip())
    except Exception as e:
        logger.error(f"Claude failed on group profile for {group_id}: {e}")
        return None

    # Check if profile exists
    existing = (
        supabase.table("group_chat_profiles")
        .select("id")
        .eq("owner_user_id", user_id)
        .eq("group_id", group_id)
        .execute()
    )

    record = {
        "owner_user_id": user_id,
        "group_id": group_id,
        "platform": "whatsapp",
        "group_name": profile_data.get("group_name"),
        "member_phones": member_phones,
        "owner_role": profile_data.get("owner_role"),
        "owner_message_ratio": round(owner_ratio, 2),
        "direct_address_patterns": profile_data.get("direct_address_patterns", {}),
        "subrelationship_signals": profile_data.get("subrelationship_signals", []),
        "recurring_topics": profile_data.get("recurring_topics", []),
        "topics_only_in_group": profile_data.get("topics_only_in_group", []),
        "group_health_score": profile_data.get("group_health_score", 0.5),
        "last_analyzed": "now()",
        "sample_size": len(messages),
    }

    if existing.data:
        supabase.table("group_chat_profiles").update(record).eq("id", existing.data[0]["id"]).execute()
    else:
        record["id"] = str(uuid.uuid4())
        supabase.table("group_chat_profiles").insert(record).execute()

    return record


def get_group_insights_for_person(user_id: str, person_name: str) -> list:
    """
    Return group chat observations about a specific person — how they behave
    in groups vs 1:1. Used to enrich the conversation agent's context.
    """
    try:
        result = (
            db.get_db()
            .table("group_chat_profiles")
            .select("group_name, direct_address_patterns, subrelationship_signals, topics_only_in_group")
            .eq("owner_user_id", user_id)
            .execute()
        )
        insights = []
        name_lower = person_name.lower()
        for profile in result.data:
            patterns = profile.get("direct_address_patterns", {}) or {}
            for name, pattern in patterns.items():
                if name_lower in name.lower():
                    insights.append(f"In group '{profile.get('group_name', 'a group')}': {pattern}")
            for signal in (profile.get("subrelationship_signals") or []):
                if name_lower in (signal.get("person_a", "") + signal.get("person_b", "")).lower():
                    insights.append(signal.get("signal", ""))
        return insights
    except Exception as e:
        logger.error(f"Could not load group insights for {person_name}: {e}")
        return []
