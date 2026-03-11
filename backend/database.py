"""
database.py — All Supabase operations in one place.
Every function that touches the database lives here.
The rest of the app calls these functions — never calls Supabase directly.
"""
from supabase import create_client, Client
from config import get_settings
from typing import Optional
import uuid
from policy_engine import guard

settings = get_settings()

# ── Supabase client (one instance, reused everywhere) ─────────────────────────
def get_db() -> Client:
    """Return the Supabase client. Called at the top of each request handler."""
    return create_client(settings.supabase_url, settings.supabase_key)


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user_by_phone(phone: str) -> Optional[dict]:
    """Look up a user by their phone number. Returns None if not found."""
    db = get_db()
    result = db.table("users").select("*").eq("phone", phone).execute()
    return result.data[0] if result.data else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Look up a user by their ID."""
    db = get_db()
    result = db.table("users").select("*").eq("id", user_id).execute()
    return result.data[0] if result.data else None


def create_user(phone: str, name: str = "") -> dict:
    """Create a new user record. Returns the created user."""
    db = get_db()
    result = db.table("users").insert({
        "id": str(uuid.uuid4()),
        "phone": phone,
        "name": name,
        "whatsapp_consented": True,     # they consented on the landing page
    }).execute()
    return result.data[0]


def update_user_google(user_id: str, google_id: str, access_token: str, refresh_token: str) -> dict:
    """Store Google OAuth tokens after the user signs in with Google."""
    db = get_db()
    result = db.table("users").update({
        "google_id": google_id,
        "google_access_token": access_token,
        "google_refresh_token": refresh_token,
    }).eq("id", user_id).execute()
    return result.data[0]


# ── People ────────────────────────────────────────────────────────────────────

def get_people_for_user(user_id: str) -> list:
    """Get all people in a user's relationship graph, ordered by closeness."""
    db = get_db()
    result = (db.table("people")
              .select("*")
              .eq("owner_user_id", user_id)
              .order("closeness_score", desc=True)
              .execute())
    return result.data


def get_person_by_id(person_id: str) -> Optional[dict]:
    """Get a single person record."""
    db = get_db()
    result = db.table("people").select("*").eq("id", person_id).execute()
    return result.data[0] if result.data else None


def upsert_person(user_id: str, person_data: dict) -> dict:
    """
    Create or update a person in the graph.
    If a person with the same name already exists for this user, update them.
    Otherwise create a new record.
    """
    db = get_db()
    # Check if person already exists by name for this user
    existing = (db.table("people")
                .select("id")
                .eq("owner_user_id", user_id)
                .eq("name", person_data.get("name", ""))
                .execute())

    if existing.data:
        # Update existing person
        person_id = existing.data[0]["id"]
        result = db.table("people").update(person_data).eq("id", person_id).execute()
        return result.data[0]
    else:
        # Create new person
        person_data["id"] = str(uuid.uuid4())
        person_data["owner_user_id"] = user_id
        result = db.table("people").insert(person_data).execute()
        return result.data[0]


def mark_relationship_bilateral(owner_user_id: str, subject_user_id: str) -> None:
    """
    When someone joins PersonalGenie, mark the relationship as bilateral.
    This means both people are on the platform and their graphs can enrich each other.
    """
    db = get_db()
    # Find the person record in owner's graph that matches the new user's phone
    subject = get_user_by_id(subject_user_id)
    if not subject:
        return

    # Update the person record to link to the subject's user account
    (db.table("people")
     .update({"subject_user_id": subject_user_id, "bilateral": True})
     .eq("owner_user_id", owner_user_id)
     .eq("phone", subject.get("phone", ""))
     .execute())


# ── Moments ───────────────────────────────────────────────────────────────────

def create_moment(user_id: str, person_id: str, suggestion: str, triggered_by: str) -> dict:
    """Save a new moment suggestion to the database."""
    # Check deceased person and emotional sensitivity before surfacing a moment
    person = get_person_by_id(person_id)
    user = get_user_by_id(user_id)
    person_is_deceased = (person.get("status") == "deceased") if person else False
    guard.check("send_evening_digest", {
        "user_id": user_id,
        "person_is_deceased": person_is_deceased,
        "suggestion_type": "reach_out" if not person_is_deceased else "memorial_acknowledgement",
        "consecutive_dismissals": (user.get("consecutive_dismissals") or 0) if user else 0,
        "proactive_suggestion_count": 0,  # individual moment creation isn't bulk proactive
    })
    db = get_db()
    result = db.table("moments").insert({
        "id": str(uuid.uuid4()),
        "owner_user_id": user_id,
        "person_id": person_id,
        "suggestion": suggestion,
        "triggered_by": triggered_by,
        "status": "pending",
    }).execute()
    return result.data[0]


def get_moments_for_user(user_id: str) -> list:
    """
    Get all pending moments for a user, ranked by priority.

    Priority order:
      1. life_event (birthday / anniversary) — highest
      2. drift_detection — relationship going quiet
      3. message_analysis — urgent signal from messages
      4. google_ingestion / voice_note — general suggestions

    Within each tier, most recent first.
    """
    db = get_db()
    result = (db.table("moments")
              .select("*, people(name, status)")
              .eq("owner_user_id", user_id)
              .eq("status", "pending")
              .order("created_at", desc=True)
              .execute())

    PRIORITY = {
        "life_event": 0,
        "drift_detection": 1,
        "message_analysis": 2,
        "voice_note": 3,
        "google_ingestion": 4,
    }

    def _rank(moment: dict) -> tuple:
        # Skip moments about deceased people — safety net
        person = moment.get("people") or {}
        if isinstance(person, dict) and person.get("status") == "deceased":
            return (99, 0)
        trigger = moment.get("triggered_by", "google_ingestion")
        return (PRIORITY.get(trigger, 5), 0)

    return sorted(result.data, key=_rank)


def update_moment_status(moment_id: str, status: str) -> None:
    """Mark a moment as done, dismissed, etc."""
    db = get_db()
    db.table("moments").update({"status": status}).eq("id", moment_id).execute()


# ── Messages ──────────────────────────────────────────────────────────────────

def save_message(user_id: str, person_id: Optional[str], platform: str, body: str, timestamp: str,
                 sender_consented: bool = True) -> dict:
    """Store a raw incoming message before processing."""
    user = get_user_by_id(user_id)
    guard.check("store_whatsapp_message", {
        "user_id": user_id,
        "data_type": platform + "_message" if platform else "message",
        "consent_status": user.get("whatsapp_consented", False) if user else False,
        "whatsapp_consented": user.get("whatsapp_consented", False) if user else False,
        "sender_consented": sender_consented,
    })
    db = get_db()
    result = db.table("messages").insert({
        "id": str(uuid.uuid4()),
        "owner_user_id": user_id,
        "from_person_id": person_id,
        "platform": platform,
        "body": body,
        "timestamp": timestamp,
        "processed": False,
    }).execute()
    return result.data[0]


def get_unprocessed_messages(user_id: str, limit: int = 50) -> list:
    """Get messages that haven't been analyzed by Claude yet."""
    db = get_db()
    result = (db.table("messages")
              .select("*, people!messages_from_person_id_fkey(name)")
              .eq("owner_user_id", user_id)
              .eq("processed", False)
              .order("timestamp", desc=True)
              .limit(limit)
              .execute())
    return result.data


def mark_messages_processed(message_ids: list) -> None:
    """Mark a batch of messages as processed after Claude analysis."""
    db = get_db()
    db.table("messages").update({"processed": True}).in_("id", message_ids).execute()


# ── Invites ───────────────────────────────────────────────────────────────────

def create_invite(inviter_user_id: str, invitee_phone: str, invitee_name: str,
                  pre_built_graph: dict) -> dict:
    """
    Create an invite record with a unique token.
    pre_built_graph contains what Genie already knows about the invitee
    from the inviter's data — this is what makes the invite message personal.
    """
    db = get_db()
    token = str(uuid.uuid4()).replace("-", "")[:16]  # short unique token for the invite link
    result = db.table("invites").insert({
        "id": str(uuid.uuid4()),
        "inviter_user_id": inviter_user_id,
        "invitee_phone": invitee_phone,
        "invitee_name": invitee_name,
        "invite_token": token,
        "status": "sent",
        "pre_built_graph": pre_built_graph,
    }).execute()
    return result.data[0]


def get_invite_by_token(token: str) -> Optional[dict]:
    """Look up an invite by its token — used when invitee taps the link."""
    db = get_db()
    result = db.table("invites").select("*").eq("invite_token", token).execute()
    return result.data[0] if result.data else None


def accept_invite(invite_id: str) -> None:
    """Mark an invite as accepted."""
    db = get_db()
    from datetime import datetime, timezone
    db.table("invites").update({
        "status": "accepted",
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", invite_id).execute()


# ── Consent ───────────────────────────────────────────────────────────────────

def log_consent(user_id: str, person_id: str, scope: list) -> dict:
    """Record that a person has consented to Genie accessing their data."""
    db = get_db()
    from datetime import datetime, timezone
    result = db.table("consent").insert({
        "id": str(uuid.uuid4()),
        "owner_user_id": user_id,
        "person_id": person_id,
        "scope": scope,
        "consented_at": datetime.now(timezone.utc).isoformat(),
        "audit_log": [],
    }).execute()
    return result.data[0]


def revoke_all_consent(phone: str) -> None:
    """
    STOP handler — immediately revoke all consent and delete all data for a phone number.
    This must complete in under 5 seconds. Called when anyone replies STOP.
    """
    db = get_db()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # Find the user
    user = get_user_by_phone(phone)
    if not user:
        return

    user_id = user["id"]

    # Revoke all consent records
    db.table("consent").update({"revoked_at": now}).eq("owner_user_id", user_id).execute()

    # Delete their messages
    db.table("messages").delete().eq("owner_user_id", user_id).execute()

    # Delete their call notes
    db.table("call_notes").delete().eq("owner_user_id", user_id).execute()

    # Clear Google tokens so we can't access their data anymore
    db.table("users").update({
        "google_access_token": None,
        "google_refresh_token": None,
        "whatsapp_consented": False,
    }).eq("id", user_id).execute()


# ── Call Notes ────────────────────────────────────────────────────────────────

def save_call_note(user_id: str, person_id: str, audio_url: str,
                   transcript: str, extracted: dict) -> dict:
    """Save a transcribed voice note with all Claude-extracted data."""
    user = get_user_by_id(user_id)
    guard.check("process_voice_note", {
        "user_id": user_id,
        "data_type": "voice_note_transcript",
        "consent_status": user.get("whatsapp_consented", False) if user else False,
        "whatsapp_consented": user.get("whatsapp_consented", False) if user else False,
        "sender_consented": True,  # voice note is always the user's own recording
    })
    db = get_db()
    result = db.table("call_notes").insert({
        "id": str(uuid.uuid4()),
        "owner_user_id": user_id,
        "person_id": person_id,
        "audio_url": audio_url,
        "transcript": transcript,
        "topics": extracted.get("topics", []),
        "emotions": extracted.get("emotions", {}),
        "extracted_memories": extracted.get("memories", []),
    }).execute()
    return result.data[0]
