"""
services/interests.py — Extract and store the user's interests from conversation.

When the user mentions something they care about — a show they're watching,
a book, a hobby, a topic — Genie captures it. This enriches the People Graph
by finding shared interests between the user and the people they love.

Lightweight: one Claude call per incoming message batch, not per message.
"""
import json
import logging
import uuid
from typing import Optional
import database as db
from services.intelligence import _call_claude

logger = logging.getLogger(__name__)

# Only extract if message contains likely interest signals
INTEREST_SIGNALS = [
    "love", "obsessed", "watching", "reading", "listening", "into",
    "recommend", "favourite", "favorite", "just finished", "started",
    "can't stop", "been playing", "been learning", "passion", "hobby",
]


def should_extract(message: str) -> bool:
    """Quick pre-filter — only call Claude if the message looks like it has interests."""
    msg_lower = message.lower()
    return any(signal in msg_lower for signal in INTEREST_SIGNALS)


def extract_from_message(user_id: str, message: str) -> list:
    """
    Extract interests from a single user message and save to the interests table.
    Returns list of extracted interest titles.
    """
    if not should_extract(message):
        return []

    system_prompt = """Extract any interests, hobbies, media, or topics the user mentions.

Return a JSON array. Each item:
{
  "title": "name of the thing",
  "item_type": "show / book / music / podcast / sport / hobby / topic / food / travel / other",
  "emotional_weight": "love / like / curious / neutral",
  "topics": ["related topic 1", "related topic 2"]
}

If nothing worth capturing, return [].
Return only valid JSON. No explanation."""

    try:
        response = _call_claude(system_prompt, f"Message: {message}")
        if "```" in response:
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        items = json.loads(response.strip())
        if not isinstance(items, list):
            return []
    except Exception as e:
        logger.error(f"Interest extraction failed: {e}")
        return []

    supabase = db.get_db()
    saved = []
    for item in items:
        title = item.get("title", "").strip()
        if not title:
            continue
        try:
            supabase.table("interests").insert({
                "id": str(uuid.uuid4()),
                "owner_user_id": user_id,
                "source": "whatsapp_conversation",
                "item_type": item.get("item_type", "other"),
                "title": title,
                "topics": item.get("topics", []),
                "emotional_weight": item.get("emotional_weight", "neutral"),
                "processed": False,
            }).execute()
            saved.append(title)
        except Exception as e:
            logger.error(f"Could not save interest '{title}': {e}")

    if saved:
        logger.info(f"Saved {len(saved)} interests for user {user_id}: {saved}")
    return saved


def get_user_interests(user_id: str, limit: int = 20) -> list:
    """Return the user's captured interests, most recent first."""
    try:
        result = (
            db.get_db()
            .table("interests")
            .select("title, item_type, topics, emotional_weight")
            .eq("owner_user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.error(f"Could not load interests for {user_id}: {e}")
        return []


def find_shared_interests(user_id: str, person_id: str) -> list:
    """
    Find interests the user has in common with a specific person.
    Compares user's interests against the person's topics array.
    Used to enrich moment suggestions.
    """
    user_interests = get_user_interests(user_id)
    person = db.get_person_by_id(person_id)
    if not person or not user_interests:
        return []

    person_topics = set(t.lower() for t in (person.get("topics") or []))
    shared = []
    for interest in user_interests:
        interest_topics = set(t.lower() for t in (interest.get("topics") or []))
        interest_topics.add(interest.get("title", "").lower())
        overlap = interest_topics & person_topics
        if overlap:
            shared.append({
                "title": interest["title"],
                "overlap": list(overlap),
            })
    return shared
