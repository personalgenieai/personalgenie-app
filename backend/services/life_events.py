"""
services/life_events.py — Birthday and anniversary detection.

Runs in two contexts:
1. After People Graph is built — extracts life events from existing people data
2. Daily scheduler — checks upcoming events and creates moments with urgency=high

Plain English: Genie knows when people's birthdays are coming up and makes
sure you never forget what matters.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional
import database as db

logger = logging.getLogger(__name__)

# How many days ahead to surface a birthday reminder
BIRTHDAY_LEAD_DAYS = 3
# How many days ahead to surface an anniversary reminder
ANNIVERSARY_LEAD_DAYS = 5


def extract_life_events_for_user(user_id: str) -> int:
    """
    Scan the user's People Graph and populate the life_events table
    from birthday and anniversary data already in their contacts.

    Called once after the People Graph is built, and again after any rebuild.
    Returns the number of events extracted.
    """
    people = db.get_people_for_user(user_id)
    supabase = db.get_db()
    extracted = 0

    for person in people:
        person_id = person["id"]
        person_name = person.get("name", "")

        # ── Birthdays from memories ─────────────────────────────────────────────
        # The People Graph stores memories with dates — look for birthday signals
        memories = person.get("memories", [])
        if isinstance(memories, list):
            for memory in memories:
                desc = (memory.get("description") or "").lower()
                if "birthday" in desc or "born" in desc or "birth" in desc:
                    date_str = memory.get("date", "")
                    parsed = _parse_date(date_str)
                    if parsed:
                        _upsert_life_event(supabase, user_id, person_id, {
                            "event_type": "birthday",
                            "title": f"{person_name}'s Birthday",
                            "description": memory.get("description", ""),
                            "date": parsed.isoformat(),
                            "is_annual": True,
                            "emotional_weight": "high",
                            "how_to_handle": "acknowledge_warmly",
                        })
                        extracted += 1
                        break  # one birthday per person is enough

        # ── Anniversary signals ─────────────────────────────────────────────────
        for memory in memories:
            desc = (memory.get("description") or "").lower()
            if any(w in desc for w in ("anniversary", "wedding", "married", "together since")):
                date_str = memory.get("date", "")
                parsed = _parse_date(date_str)
                if parsed:
                    _upsert_life_event(supabase, user_id, person_id, {
                        "event_type": "anniversary",
                        "title": f"Anniversary with {person_name}",
                        "description": memory.get("description", ""),
                        "date": parsed.isoformat(),
                        "is_annual": True,
                        "emotional_weight": "high",
                        "how_to_handle": "acknowledge_warmly",
                    })
                    extracted += 1
                    break

    logger.info(f"Extracted {extracted} life events for user {user_id}")
    return extracted


def extract_from_contacts(user_id: str, contacts: list) -> int:
    """
    Extract birthdays directly from raw Google Contacts data
    (called during ingestion before People Graph is built).

    contacts: list of dicts with keys: name, birthday, phones, emails
    Returns number of events saved.
    """
    supabase = db.get_db()
    people = db.get_people_for_user(user_id)
    people_by_name = {p["name"].lower(): p for p in people}
    extracted = 0

    for contact in contacts:
        birthday_str = contact.get("birthday")
        name = contact.get("name", "")
        if not birthday_str or not name:
            continue

        # Find the matching person record
        person = people_by_name.get(name.lower())
        if not person:
            # Try partial match
            person = next(
                (p for p in people if name.lower() in p["name"].lower()),
                None
            )
        if not person:
            continue

        parsed = _parse_contact_birthday(birthday_str)
        if not parsed:
            continue

        _upsert_life_event(supabase, user_id, person["id"], {
            "event_type": "birthday",
            "title": f"{name}'s Birthday",
            "description": f"Birthday on {parsed.strftime('%B %d')}",
            "date": parsed.isoformat(),
            "is_annual": True,
            "emotional_weight": "high",
            "how_to_handle": "acknowledge_warmly",
        })
        extracted += 1

    logger.info(f"Extracted {extracted} birthdays from contacts for user {user_id}")
    return extracted


def check_upcoming_events(user_id: str) -> list:
    """
    Find all life events happening in the next BIRTHDAY_LEAD_DAYS days.
    Creates a moment for each one with urgency=high.

    Called daily by the scheduler. Returns list of moments created.
    """
    supabase = db.get_db()
    today = date.today()
    moments_created = []

    try:
        result = (
            supabase.table("life_events")
            .select("*")
            .eq("owner_user_id", user_id)
            .execute()
        )
        events = result.data
    except Exception as e:
        logger.error(f"Could not load life events for user {user_id}: {e}")
        return []

    for event in events:
        event_date = _parse_date(event.get("date", ""))
        if not event_date:
            continue

        is_annual = event.get("is_annual", False)
        lead_days = BIRTHDAY_LEAD_DAYS if event.get("event_type") == "birthday" else ANNIVERSARY_LEAD_DAYS

        # For annual events, compare month/day against today's year
        if is_annual:
            this_year_date = event_date.replace(year=today.year)
            # If it already passed this year, check next year
            if this_year_date < today:
                this_year_date = this_year_date.replace(year=today.year + 1)
            days_away = (this_year_date - today).days
        else:
            days_away = (event_date - today).days

        if 0 <= days_away <= lead_days:
            # Check if we already created a moment for this event recently
            already_created = _moment_exists_for_event(supabase, user_id, event)
            if already_created:
                continue

            suggestion = _build_suggestion(event, days_away)
            try:
                moment = db.create_moment(
                    user_id=user_id,
                    person_id=event["person_id"],
                    suggestion=suggestion,
                    triggered_by="life_event",
                )
                # Mark event as acknowledged
                supabase.table("life_events").update({
                    "last_acknowledged_at": datetime.utcnow().isoformat()
                }).eq("id", event["id"]).execute()

                moments_created.append(moment)
                logger.info(
                    f"Created moment for {event.get('title')} "
                    f"({days_away} days away) for user {user_id}"
                )
            except Exception as e:
                logger.error(f"Failed to create moment for event {event.get('id')}: {e}")

    return moments_created


def run_life_events_check_for_all_users() -> int:
    """
    Called by the daily scheduler (2am UTC = 6pm PT).
    Checks upcoming events for every user and creates urgent moments.
    Returns total moments created.
    """
    try:
        result = db.get_db().table("users").select("id").execute()
        users = result.data
    except Exception as e:
        logger.error(f"Could not load users for life events check: {e}")
        return 0

    total = 0
    for user in users:
        try:
            moments = check_upcoming_events(user["id"])
            total += len(moments)
        except Exception as e:
            logger.error(f"Life events check failed for user {user['id']}: {e}")

    logger.info(f"Life events check complete: {total} moments created across {len(users)} users")
    return total


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(date_str: str) -> Optional[date]:
    """Parse a date string in common formats into a date object."""
    if not date_str:
        return None
    formats = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
               "%m/%d/%Y", "%m/%d", "%B %d, %Y", "%B %d"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str[:len(fmt) + 5], fmt).date()
        except ValueError:
            continue
    return None


def _parse_contact_birthday(birthday_str: str) -> Optional[date]:
    """
    Parse birthday from Google Contacts format.
    Examples: "4/15", "1990-4-15", "4/15/1990"
    """
    if not birthday_str:
        return None

    # Format: "YYYY-M/D" or "M/D" or "YYYY-MM-DD"
    parts = birthday_str.replace("-", "/").split("/")
    try:
        if len(parts) == 3:
            # Could be YYYY/M/D or M/D/YYYY
            if len(parts[0]) == 4:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            else:
                return date(2000, int(parts[0]), int(parts[1]))  # placeholder year
        elif len(parts) == 2:
            return date(2000, int(parts[0]), int(parts[1]))  # no year
    except (ValueError, IndexError):
        pass
    return _parse_date(birthday_str)


def _upsert_life_event(supabase, user_id: str, person_id: str, event_data: dict) -> None:
    """Insert a life event, skipping if one already exists for this person + type."""
    try:
        existing = (
            supabase.table("life_events")
            .select("id")
            .eq("owner_user_id", user_id)
            .eq("person_id", person_id)
            .eq("event_type", event_data["event_type"])
            .execute()
        )
        if existing.data:
            return  # already have this event

        import uuid
        supabase.table("life_events").insert({
            "id": str(uuid.uuid4()),
            "owner_user_id": user_id,
            "person_id": person_id,
            **event_data,
        }).execute()
    except Exception as e:
        logger.error(f"Could not upsert life event: {e}")


def _moment_exists_for_event(supabase, user_id: str, event: dict) -> bool:
    """Check if we already created a moment for this event in the last 7 days."""
    try:
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        result = (
            supabase.table("moments")
            .select("id")
            .eq("owner_user_id", user_id)
            .eq("person_id", event["person_id"])
            .eq("triggered_by", "life_event")
            .gte("created_at", cutoff)
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False


def _build_suggestion(event: dict, days_away: int) -> str:
    """Generate a warm, specific suggestion for an upcoming life event."""
    title = event.get("title", "")
    event_type = event.get("event_type", "birthday")

    if days_away == 0:
        if event_type == "birthday":
            return f"Today is {title}. Send a message — even a short one means everything."
        return f"Today is {title}. Reach out and let them know you're thinking of them."
    elif days_away == 1:
        return f"{title} is tomorrow. A quick note today lands warmer than one on the day."
    else:
        return f"{title} is in {days_away} days. You have time to make it feel personal."
