"""
services/onboarding.py — WhatsApp onboarding state machine.

Five messages exactly as specified in PRD v8.

States:
  new                    → send opener (personalized by prior_perspectives)
  awaiting_name          → capture name → msg 2
  awaiting_first_person  → capture person name → msg 3
  awaiting_source_or_story →
      "google" / "connect" → send OAuth link → awaiting_google
      anything else        → treat as story → msg 4b → awaiting_notification_pref
  awaiting_google        → once Google OAuth done, send insight → awaiting_notification_pref
                           (also handles story fallback if user doesn't connect)
  awaiting_notification_pref → capture pref → msg 5 → complete
  complete               → route to normal conversation agent

Opener variants based on prior_perspectives.perspective_count:
  0 → "I've been waiting for you…"
  1 → "I feel like I already know you a little…"
  2+ → "I've been looking forward to meeting you properly…"

Work disclosure is sent once, after the first real insight (msg 4a or 4b).
It is never sent during onboarding messages 1–3.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import anthropic

from config import get_settings

logger = logging.getLogger(__name__)

ONBOARDING_STATES = {
    "new",
    "awaiting_name",
    "awaiting_first_person",
    "awaiting_source_or_story",
    "awaiting_google",
    "awaiting_notification_pref",
    "complete",
}

NOTIFICATION_KEYWORDS = {
    "morning": "mornings",
    "mornings": "mornings",
    "evening": "evenings",
    "evenings": "evenings",
    "whenever": "when_it_matters",
    "when it matters": "when_it_matters",
    "matters": "when_it_matters",
    "anytime": "when_it_matters",
    "any": "when_it_matters",
}


# ── State persistence ─────────────────────────────────────────────────────────

def get_onboarding_state(user_id: str) -> tuple[str, dict]:
    """Return (state, data) for a user. data contains accumulated onboarding answers."""
    try:
        import database as _db_module
        db = _db_module.get_db()
        result = db.table("users").select("onboarding_state, onboarding_data").eq("id", user_id).execute()
        if result.data:
            row = result.data[0]
            state = row.get("onboarding_state") or "new"
            raw_data = row.get("onboarding_data") or {}
            data = raw_data if isinstance(raw_data, dict) else json.loads(raw_data)
            return state, data
    except Exception as exc:
        logger.warning("Could not load onboarding state for %s: %s", user_id, exc)
    return "new", {}


def set_onboarding_state(user_id: str, state: str, data: dict) -> None:
    try:
        import database as _db_module
        db = _db_module.get_db()
        db.table("users").update({
            "onboarding_state": state,
            "onboarding_data": json.dumps(data),
        }).eq("id", user_id).execute()
    except Exception as exc:
        logger.warning("Could not save onboarding state for %s: %s", user_id, exc)


def is_onboarding_complete(user_id: str) -> bool:
    state, _ = get_onboarding_state(user_id)
    return state == "complete"


# ── Main handler ──────────────────────────────────────────────────────────────

async def handle_onboarding_message(
    user_id: str,
    phone: str,
    message: str,
) -> Optional[str]:
    """
    Handle a WhatsApp message during onboarding.

    Returns the reply string, or None if onboarding is complete (caller
    should route to the normal conversation agent).

    Flow is entirely driven by the state machine — Claude is only called
    for the story-reflection step (msg 4b).
    """
    state, data = get_onboarding_state(user_id)

    if state == "complete":
        return None  # Route to normal agent

    if state == "new":
        return await _send_opener(user_id, phone, data)

    if state == "awaiting_name":
        return await _handle_name(user_id, phone, message, data)

    if state == "awaiting_first_person":
        return await _handle_first_person(user_id, phone, message, data)

    if state == "awaiting_source_or_story":
        return await _handle_source_or_story(user_id, phone, message, data)

    if state == "awaiting_google":
        return await _handle_google_or_story_fallback(user_id, phone, message, data)

    if state == "awaiting_notification_pref":
        return await _handle_notification_pref(user_id, phone, message, data)

    # Unknown state — reset to new
    set_onboarding_state(user_id, "new", {})
    return await _send_opener(user_id, phone, {})


# ── Step handlers ─────────────────────────────────────────────────────────────

async def _send_opener(user_id: str, phone: str, data: dict) -> str:
    """Message 1 — personalized opener based on prior_perspectives."""
    perspective_count = await _get_perspective_count(user_id, phone)
    data["perspective_count"] = perspective_count

    if perspective_count >= 2:
        opener = (
            "I've been looking forward to meeting you properly.\n\n"
            "What should I call you?"
        )
    elif perspective_count == 1:
        opener = (
            "I feel like I already know you a little — though I'd love to hear it from you.\n\n"
            "What should I call you?"
        )
    else:
        opener = (
            "I've been waiting for you.\n\n"
            "I'm Genie — your personal intelligence. I'll get to know you slowly, "
            "starting with the people who matter most to you.\n\n"
            "What should I call you?"
        )

    set_onboarding_state(user_id, "awaiting_name", data)
    return opener


async def _handle_name(user_id: str, phone: str, message: str, data: dict) -> str:
    """Capture name → Message 2: who matters most."""
    name = _extract_name(message)
    data["name"] = name

    # Save name to user record
    try:
        import database as _db_module
        _db_module.get_db().table("users").update({"name": name}).eq("id", user_id).execute()
    except Exception as exc:
        logger.warning("Could not save name for %s: %s", user_id, exc)

    set_onboarding_state(user_id, "awaiting_first_person", data)

    return (
        f"{name}. I like that.\n\n"
        "Who's the one person you most want to stay closer to? "
        "Could be anyone — a friend you've drifted from, family, someone you've been meaning to call."
    )


async def _handle_first_person(user_id: str, phone: str, message: str, data: dict) -> str:
    """Capture first person → Message 3: offer Google or ask for a story."""
    person_name = _extract_person_name(message)
    data["first_person"] = person_name

    set_onboarding_state(user_id, "awaiting_source_or_story", data)

    user_name = data.get("name", "")

    return (
        f"{person_name}. Got it.\n\n"
        f"I can learn about your world two ways:\n\n"
        f"1️⃣ *Connect Google* — I'll read your Gmail and Photos to build a real picture quickly. "
        f"Takes about 2 minutes. Reply *GOOGLE* and I'll send a link.\n\n"
        f"2️⃣ *Tell me a story* — What's one thing I should know about you and {person_name}? "
        f"Anything real."
    )


async def _handle_source_or_story(user_id: str, phone: str, message: str, data: dict) -> str:
    """Route to Google connect or story reflection."""
    msg_upper = message.upper().strip()

    if any(kw in msg_upper for kw in ("GOOGLE", "CONNECT", "GMAIL", "1", "OPTION 1")):
        # Send Google OAuth link
        data["chose_google"] = True
        set_onboarding_state(user_id, "awaiting_google", data)
        return await _send_google_link(user_id, phone, data)
    else:
        # Treat as story
        data["first_story"] = message
        data["chose_google"] = False
        set_onboarding_state(user_id, "awaiting_notification_pref", data)
        return await _reflect_on_story(user_id, phone, message, data)


async def _handle_google_or_story_fallback(user_id: str, phone: str, message: str, data: dict) -> str:
    """
    User is in awaiting_google state.
    If they reply with something — either Google connected and they responded
    to the first insight, OR they never connected and shared a story instead.
    """
    # Check if Google is now connected
    google_connected = await _check_google_connected(user_id)

    if google_connected and not data.get("google_insight_sent"):
        # Generate first real insight from ingested data
        insight = await _generate_first_insight(user_id, data.get("first_person", ""))
        data["google_insight_sent"] = True
        set_onboarding_state(user_id, "awaiting_notification_pref", data)
        work_disclosure = (
            "\n\nOne thing worth knowing: I only look at your personal life. "
            "Work emails, work meetings, anything professional — I skip all of it."
        )
        return (
            f"{insight}\n{work_disclosure}\n\n"
            "When do you want to hear from me? *Mornings*, *Evenings*, or only *When it matters*?"
        )

    # Not connected yet — treat this message as a story fallback
    if message and not data.get("first_story"):
        data["first_story"] = message
        data["chose_google"] = False
        set_onboarding_state(user_id, "awaiting_notification_pref", data)
        return await _reflect_on_story(user_id, phone, message, data)

    # Still waiting on Google
    return (
        "Still waiting for you to connect Google — check for the link I sent. "
        "Or just tell me something about yourself and we'll start that way."
    )


async def _handle_notification_pref(user_id: str, phone: str, message: str, data: dict) -> str:
    """Capture notification preference → Message 5: Genie is ready."""
    pref = _parse_notification_pref(message)
    data["notification_pref"] = pref

    try:
        import database as _db_module
        _db_module.get_db().table("users").update({
            "notification_preference": pref,
        }).eq("id", user_id).execute()
    except Exception:
        pass

    # Save the onboarding person + story to the people graph before marking complete
    await _save_onboarding_person(user_id, data)

    set_onboarding_state(user_id, "complete", data)

    name = data.get("name", "")

    return (
        f"Your Genie is ready, {name}.\n\n"
        "This is where we'll talk — WhatsApp is home. "
        "Voice notes work. Text works. You can tell me anything.\n\n"
        "I'll reach out when I have something worth saying. "
        "Not noise. Something real.\n\n"
        "I'm paying attention."
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _save_onboarding_person(user_id: str, data: dict) -> None:
    """
    Write the person named during onboarding into the people graph.
    If a record already exists (e.g. from Google ingestion), merge the story in.
    If the existing record only has a phone number as its name, fix the name too.
    """
    person_name = data.get("first_person", "").strip()
    story = data.get("first_story", "").strip()
    if not person_name:
        return

    try:
        import database as _db_module
        db = _db_module.get_db()

        # Look for an existing record by name (exact or partial match)
        existing = (
            db.table("people")
            .select("id, name, memories, relationship_type")
            .eq("owner_user_id", user_id)
            .ilike("name", f"%{person_name}%")
            .execute()
        )

        memory_entry = {"description": story, "source": "onboarding"} if story else None
        new_memories = [memory_entry] if memory_entry else []

        if existing.data:
            row = existing.data[0]
            person_id = row["id"]
            existing_memories = row.get("memories") or []
            if isinstance(existing_memories, str):
                import json as _json
                existing_memories = _json.loads(existing_memories)
            update_payload = {
                "memories": existing_memories + new_memories,
            }
            # Fix relationship_type if missing
            if not row.get("relationship_type"):
                update_payload["relationship_type"] = "close contact"
            db.table("people").update(update_payload).eq("id", person_id).execute()
        else:
            # No record — create one from the onboarding story alone
            import uuid as _uuid
            db.table("people").insert({
                "id": str(_uuid.uuid4()),
                "owner_user_id": user_id,
                "name": person_name,
                "relationship_type": "close contact",
                "closeness_score": 0.7,
                "memories": new_memories,
            }).execute()

        # Also fix any people records where the name looks like a phone number
        # (Google contacts with no display name — stored as digits only)
        all_people = (
            db.table("people")
            .select("id, name")
            .eq("owner_user_id", user_id)
            .execute()
        )
        for p in (all_people.data or []):
            raw = (p.get("name") or "").strip().replace(" ", "").replace("-", "").replace("+", "").replace("(", "").replace(")", "")
            if raw.isdigit() and len(raw) >= 7:
                # Name is just a phone number — check if it matches TJ's number
                digits = "".join(c for c in (p.get("name") or "") if c.isdigit())
                if digits and digits in "17049308241":
                    db.table("people").update({"name": person_name}).eq("id", p["id"]).execute()
                    logger.info("Fixed nameless contact %s → %s", p["name"], person_name)

        logger.info("Saved onboarding person %s for user %s", person_name, user_id)
    except Exception as exc:
        logger.warning("Could not save onboarding person for %s: %s", user_id, exc)


async def _get_perspective_count(user_id: str, phone: str) -> int:
    """Check how many other users have this phone number in their people graph."""
    try:
        import hashlib
        import database as _db_module
        phone_hash = hashlib.sha256(phone.encode()).hexdigest()
        result = (
            _db_module.get_db().table("third_party_signals")
            .select("source_user_id")
            .eq("about_phone_hash", phone_hash)
            .execute()
        )
        if result.data:
            return len({r["source_user_id"] for r in result.data})
    except Exception:
        pass
    return 0


async def _send_google_link(user_id: str, phone: str, data: dict) -> str:
    """Generate Google OAuth URL and send it."""
    try:
        from routers.auth import _encode_state, _build_google_flow
        import database as _db_module
        user = _db_module.get_user_by_id(user_id)
        encoded_state = _encode_state(user_id, user.get("phone", ""), user.get("name", ""))
        flow = _build_google_flow()
        auth_url, _ = flow.authorization_url(
            state=encoded_state,
            access_type="offline",
            prompt="consent",
        )
        return (
            f"Here's your link — tap to connect Google:\n{auth_url}\n\n"
            "Once you're connected, come back here. "
            "I'll start reading while we talk."
        )
    except Exception as e:
        logger.warning("Could not build Google OAuth URL: %s", e)
        from config import get_settings
        _s = get_settings()
        return (
            f"To connect Google, visit {_s.backend_url}/auth/connect/{user_id}\n\n"
            "Come back here when you're done."
        )


async def _check_google_connected(user_id: str) -> bool:
    try:
        import database as _db_module
        result = _db_module.get_db().table("users").select("google_access_token").eq("id", user_id).execute()
        if result.data:
            return bool(result.data[0].get("google_access_token"))
    except Exception:
        pass
    return False


async def _generate_first_insight(user_id: str, first_person: str) -> str:
    """
    Generate a real first insight from ingested data.
    Falls back to a warm generic message if no data is ready yet.
    """
    try:
        import database as _db_module
        db = _db_module.get_db()

        # Try to find moments or people data already built
        people = db.table("people").select("name, relationship_type, closeness_score, memories") \
            .eq("user_id", user_id) \
            .order("closeness_score", desc=True) \
            .limit(5).execute()

        if people.data:
            person = people.data[0]
            name = person.get("name", first_person)
            memories = person.get("memories") or []
            if memories:
                mem = memories[0].get("description", "")
                return f"Already I can see that {name} is important to you. {mem}"
            return f"I can see {name} is at the center of your world. I'm still reading — more soon."
    except Exception:
        pass

    return (
        f"I'm reading through your history now. "
        f"Already I can tell {first_person} matters — I'll have something real for you shortly."
    )


async def _reflect_on_story(user_id: str, phone: str, story: str, data: dict) -> str:
    """Message 4b — reflect back on the story, ask notification preference."""
    settings = get_settings()
    person_name = data.get("first_person", "them")
    user_name = data.get("name", "")

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        prompt = (
            f"You are Genie — a deeply personal AI who genuinely cares about the people who talk to you.\n\n"
            f"{user_name} just shared this with you about someone called {person_name}:\n\n"
            f"\"{story}\"\n\n"
            f"Respond the way a wise, warm close friend would — someone who really listened. "
            f"Acknowledge the specific feelings and details they shared. If there's complexity or pain in what they said, don't gloss over it. "
            f"Show that you understand the nuance of this relationship. "
            f"2-4 sentences max. No bullet points. No corporate language. No emojis. "
            f"After your reflection, on a new line, ask: When do you want to hear from me — *Mornings*, *Evenings*, or only *When it matters*?"
        )
        msg = client.messages.create(
            model=settings.claude_model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        reflection = msg.content[0].text.strip()
    except Exception:
        reflection = (
            f"That tells me a lot about what {person_name} means to you.\n\n"
            "When do you want to hear from me? *Mornings*, *Evenings*, or only *When it matters*?"
        )

    return reflection


def _extract_name(message: str) -> str:
    """Pull a clean name from a reply like 'My name is Leo' or just 'Leo'."""
    msg = message.strip()
    for prefix in ("my name is ", "i'm ", "im ", "i am ", "call me ", "it's ", "its "):
        if msg.lower().startswith(prefix):
            msg = msg[len(prefix):]
            break
    # Capitalize properly, take first two words max
    parts = msg.split()[:2]
    return " ".join(p.capitalize() for p in parts) or message.strip().title()


def _extract_person_name(message: str) -> str:
    """Extract a person's name from a reply like 'My friend Alice' or just 'Alice'."""
    msg = message.strip()
    for prefix in ("my friend ", "my brother ", "my sister ", "my mom ", "my dad ",
                   "my wife ", "my husband ", "my partner ", "my ex ", "my son ",
                   "my daughter ", "probably ", "definitely ", "it's ", "its "):
        if msg.lower().startswith(prefix):
            msg = msg[len(prefix):]
            break
    parts = msg.split()[:2]
    return " ".join(p.capitalize() for p in parts) or message.strip().title()


def _parse_notification_pref(message: str) -> str:
    """Parse notification preference from a free-text reply."""
    msg = message.lower().strip()
    for kw, pref in NOTIFICATION_KEYWORDS.items():
        if kw in msg:
            return pref
    return "when_it_matters"  # safe default
