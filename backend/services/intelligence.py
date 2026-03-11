"""
services/intelligence.py — All Claude API calls live here.

Plain English: this is the brain. It takes raw data (photos, emails, messages,
voice notes) and turns it into people insights and moment suggestions.
Claude never cites its sources — it simply knows, like a wise friend.
"""
import json
import logging
import re
from anthropic import Anthropic
from config import get_settings
import database as db


def _safe_date(value) -> None:
    """
    Return a Postgres-safe date string (YYYY-MM-DD or YYYY-MM) or None.
    Rejects free-text values that would cause a 400 from Supabase.
    """
    if not value or not isinstance(value, str):
        return None
    # Accept YYYY, YYYY-MM, or YYYY-MM-DD
    if re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", value.strip()):
        v = value.strip()
        # Pad YYYY → YYYY-01-01, YYYY-MM → YYYY-MM-01 for DATE column
        if re.match(r"^\d{4}$", v):
            return f"{v}-01-01"
        if re.match(r"^\d{4}-\d{2}$", v):
            return f"{v}-01"
        return v
    return None

logger = logging.getLogger(__name__)
settings = get_settings()

# One Anthropic client, reused for all calls
_client = Anthropic(api_key=settings.anthropic_api_key)


def _call_claude(system_prompt: str, user_message: str) -> str:
    """
    Make a single Claude API call and return the text response.
    All Claude calls in this file go through here.
    """
    response = _client.messages.create(
        model=settings.claude_model,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


def build_people_graph(user_id: str, ingestion_data: dict, session_id: str | None = None) -> list:
    """
    Take everything from Google ingestion and build a complete People Graph.

    Sends Photos + Gmail + Contacts to Claude and gets back structured
    relationship data: closeness scores, memories, moment suggestions.

    Returns a list of person records ready to save to Supabase.
    """

    system_prompt = """You are the relationship intelligence engine for PersonalGenie.
You have been given a person's Google Photos people albums, Gmail contact frequency data,
and Google Contacts.

Build a People Graph for this user. Return a JSON array of up to 100 people.

CRITICAL: You MUST include family members. Look for:
- Contacts saved with family labels (Mom, Dad, Papa, Mama, Brother, Sister, Bhai, Didi, Uncle, Aunt, Nana, Nani, Dada, Dadi, Chacha, Chachi, Masi, Mausa, Bua, Fufa, Cousin, etc.)
- Contacts sharing the user's last name
- Anyone with an obvious family relationship in their name or notes
Family members should have closeness_score 0.85-1.0 regardless of contact frequency.

For each person return exactly this structure:
{
  "name": "Full name",
  "relationship_type": "Brother / Best friend / College roommate / etc — be specific",
  "closeness_score": 0.0 to 1.0,
  "last_contact": "approximate date or timeframe",
  "topics": ["specific shared interest 1", "specific shared interest 2"],
  "memories": [
    {
      "description": "specific memorable shared moment or fact",
      "date": "approximate date if known",
      "source": "photos / gmail / contacts"
    }
  ],
  "suggested_moments": [
    {
      "suggestion": "one specific, warm, actionable thing they could do right now",
      "urgency": "high / medium / low",
      "trigger": "what in the data made you suggest this"
    }
  ],
  "insight_line": "one warm, specific human insight — not generic. Something that would make the user say 'how did it know that?'"
}

Rules:
- Always include family first, then closest friends, then significant professional contacts.
- Be specific and personal. Never generic.
- Every insight must be grounded in actual data.
- Genie never cites its sources. Write insights in first person as if Genie simply knows.
- The insight_line must feel like something a wise friend would say.
- Return only valid JSON. No markdown. No explanation."""

    # Pre-sort contacts: family members first, then the rest
    all_contacts = ingestion_data.get('contacts', {}).get('contacts', [])
    family_keywords = {
        'mom', 'dad', 'papa', 'mama', 'mother', 'father', 'brother', 'sister',
        'bhai', 'didi', 'nana', 'nani', 'dada', 'dadi', 'chacha', 'chachi',
        'masi', 'mausa', 'bua', 'fufa', 'uncle', 'aunt', 'cousin', 'gupta',
        'son', 'daughter', 'wife', 'husband', 'spouse', 'bro', 'sis'
    }

    def is_family(contact):
        name = (contact.get('name') or '').lower()
        notes = (contact.get('notes') or '').lower()
        return any(kw in name or kw in notes for kw in family_keywords)

    family_contacts = [c for c in all_contacts if is_family(c)]
    other_contacts = [c for c in all_contacts if not is_family(c)]
    # Family first, then fill up to 60 total
    selected_contacts = family_contacts[:50] + other_contacts[:max(0, 300 - len(family_contacts[:50]))]

    # Cross-reference Gmail email addresses with contacts to attach names.
    # Without this, Claude sees "john@gmail.com" but can't match it to "John Smith"
    # in the contacts list — so Gmail data never influences the People Graph.
    email_to_name: dict = {}
    for c in all_contacts:
        for email in c.get("emails", []):
            if email:
                email_to_name[email.lower()] = c.get("name", "")

    gmail_contacts_raw = ingestion_data.get('gmail', {}).get('frequent_contacts', [])
    gmail_enriched = []
    for gc in gmail_contacts_raw:
        email = gc.get("email", "").lower()
        enriched = dict(gc)
        matched_name = email_to_name.get(email, "")
        if matched_name:
            enriched["resolved_name"] = matched_name
        gmail_enriched.append(enriched)

    user_message = f"""Here is the Google data for this user:

PHOTOS PEOPLE ALBUMS (ranked by photo count):
{json.dumps(ingestion_data.get('photos', {}).get('people_albums', []), indent=2)}

GMAIL FREQUENT CONTACTS (email_count = emails sent to them; resolved_name = matched from Contacts):
{json.dumps(gmail_enriched, indent=2)}

GOOGLE CONTACTS (family contacts listed first):
{json.dumps(selected_contacts, indent=2)}

IMPORTANT: For each person, if they appear in the Gmail frequent contacts list (matched by email
or resolved_name), you MUST include at least one memory with source="gmail" that reflects their
email frequency, subject patterns, or communication habits. Do not leave Gmail data unused.

Build the People Graph now."""

    from services.ingestion_bus import get_session, broadcast_sync

    # Resolve session: use passed-in value, or look up from bus
    active_session = session_id or get_session(user_id)

    def _emit(progress: int, message: str, insight: str | None = None,
              people_found: int = 0) -> None:
        if active_session:
            broadcast_sync(
                active_session, "analyzing", "analyzing", progress, message,
                insight=insight, people_found=people_found, user_id=user_id,
            )

    _emit(75, "Reading your relationships…")

    try:
        response_text = _call_claude(system_prompt, user_message)

        # Parse JSON response — Claude returns a clean JSON array
        # Handle case where Claude wraps in ```json ... ```
        if "```" in response_text:
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]

        people = json.loads(response_text.strip())
        total = len(people)
        _emit(78, f"Genie found {total} people who matter to you.", people_found=total)

        # Save each person to Supabase — broadcast their insight as we go
        saved_people = []
        for i, person in enumerate(people):
            saved = db.upsert_person(user_id, {
                "name":             person.get("name", ""),
                "relationship_type": person.get("relationship_type", ""),
                "closeness_score":  person.get("closeness_score", 0.5),
                "topics":           person.get("topics", []),
                "memories":         person.get("memories", []),
                "suggested_moments": person.get("suggested_moments", []),
            })

            # Also save top moment to moments table for the feed
            moments = person.get("suggested_moments", [])
            if moments and saved:
                db.create_moment(
                    user_id=user_id,
                    person_id=saved["id"],
                    suggestion=moments[0]["suggestion"],
                    triggered_by="google_ingestion"
                )

            # Broadcast this person's insight to the iOS live feed
            insight_line = person.get("insight_line", "").strip()
            if insight_line and active_session:
                progress_pct = 80 + int((i / max(total, 1)) * 18)  # 80–98%
                _emit(
                    progress_pct,
                    person.get("name", "Someone close to you"),
                    insight=insight_line,
                    people_found=i + 1,
                )

            saved_people.append({**saved, "insight_line": insight_line})

        # Final broadcast — 100%
        _emit(100, "Your People Graph is ready.", people_found=total)

        logger.info(f"Built People Graph for user {user_id}: {len(saved_people)} people")
        return saved_people

    except Exception as e:
        logger.error(f"Error building People Graph: {e}")
        return []


def get_first_magic_moment(user_id: str, user_name: str) -> str:
    """
    After the People Graph is built, surface the single most meaningful insight.
    This is the message that makes the product feel magical.

    Returns a WhatsApp-ready message string.
    """
    people = db.get_people_for_user(user_id)
    if not people:
        return f"Your People Graph is taking shape, {user_name.split()[0]}. Give me a moment ✨"

    # Find the person with the highest closeness score and a good insight
    top_person = people[0]
    moments = top_person.get("suggested_moments", [])
    memories = top_person.get("memories", [])
    name = top_person.get("name", "someone close to you")

    system_prompt = """You are Personal Genie — a wise, warm presence that knows what matters.
Write a single WhatsApp message (3-4 sentences max) that is the user's first experience of the magic.

Rules:
- Never say "based on your photos" or "I noticed from Gmail" — just know it.
- Be specific. Reference actual data.
- Warm and personal — like a message from a wise friend, not a tech product.
- End with one gentle question or observation that invites a reply.
- No emojis spam — one or two maximum.
- This must make them think: "how did it know that?"
"""

    user_message = f"""The user is {user_name}.
Their closest person is {name} ({top_person.get('relationship_type', 'someone close')}).

What Genie knows about them:
- Memories: {json.dumps(memories[:3])}
- Suggested moments: {json.dumps(moments[:2])}
- Closeness score: {top_person.get('closeness_score', 0.8)}

Write the first magic moment message now."""

    try:
        return _call_claude(system_prompt, user_message)
    except Exception as e:
        logger.error(f"Error generating first magic moment: {e}")
        # Fallback if Claude fails
        return f"I found something worth knowing about {name}. When did you two last speak?"


def analyze_messages(user_id: str, messages: list) -> dict:
    """
    Take a batch of WhatsApp messages and extract relationship intelligence.
    Updates people records and creates new moment suggestions.

    Called every 30 minutes for each user who has unprocessed messages.
    """
    if not messages:
        return {}

    # Format messages for Claude
    messages_text = "\n".join([
        f"[{m.get('timestamp', '')}] {m.get('people', {}).get('name', 'Unknown')}: {m.get('body', '')}"
        for m in messages
    ])

    system_prompt = """You are the relationship intelligence engine for PersonalGenie.
Analyze these WhatsApp messages and return structured JSON.

Return exactly:
{
  "people_updates": [
    {
      "person_name": "name",
      "emotions": ["specific emotion 1", "specific emotion 2"],
      "new_memories": ["specific fact worth remembering"],
      "topics": ["topic 1"],
      "closeness_delta": -0.1 to +0.1,
      "urgent_moment": null or "specific actionable suggestion — only if genuinely urgent"
    }
  ],
  "relationships_signals": "one sentence summary of what's happening in these relationships"
}

Rules:
- Be specific. Reference actual words from the messages.
- Emotions must be nuanced — not "happy" but "quietly proud" or "anxious about something unsaid".
- Only flag urgent moments if something genuinely time-sensitive or important.
- Return only valid JSON."""

    try:
        response_text = _call_claude(system_prompt, f"Messages to analyze:\n{messages_text}")

        if "```" in response_text:
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]

        extracted = json.loads(response_text.strip())

        # Update people records with new data
        people = db.get_people_for_user(user_id)
        people_by_name = {p["name"].lower(): p for p in people}

        for update in extracted.get("people_updates", []):
            person_name = update.get("person_name", "").lower()
            person = people_by_name.get(person_name)
            if not person:
                continue

            # Update emotions history and memories
            existing_memories = person.get("memories", [])
            new_memories = [
                {"description": m, "source": "whatsapp"}
                for m in update.get("new_memories", [])
            ]

            from datetime import datetime, timezone
            db.upsert_person(user_id, {
                "name": person["name"],
                "closeness_score": max(0.0, min(1.0,
                    person.get("closeness_score", 0.5) + update.get("closeness_delta", 0)
                )),
                "memories": existing_memories + new_memories,
                "last_meaningful_exchange": datetime.now(timezone.utc).isoformat(),
            })

            # Create urgent moment if flagged
            if update.get("urgent_moment"):
                db.create_moment(
                    user_id=user_id,
                    person_id=person["id"],
                    suggestion=update["urgent_moment"],
                    triggered_by="message_analysis"
                )

        return extracted

    except Exception as e:
        logger.error(f"Error analyzing messages: {e}")
        return {}


def process_voice_note(user_id: str, person_name: str, transcript: str) -> dict:
    """
    Extract relationship intelligence from a voice note transcript.
    Updates the person's profile in Supabase.
    """
    system_prompt = f"""You are the relationship intelligence engine for PersonalGenie.
This is a personal voice note about a conversation with {person_name}.

Return structured JSON:
{{
  "topics": ["specific topic 1", "specific topic 2"],
  "emotions": {{
    "other_person_state": "their emotional state as perceived by the speaker",
    "speaker_perception": "what the speaker seems to feel about this person"
  }},
  "memories": ["specific fact worth permanently remembering"],
  "urgency_flags": ["anything concerning or time-sensitive — null if nothing"],
  "suggested_followup": {{
    "suggestion": "specific follow-up action",
    "timing": "when to do it"
  }}
}}

Rules:
- Be specific. Every detail matters.
- Return only valid JSON."""

    try:
        response_text = _call_claude(system_prompt, f"Voice note transcript:\n{transcript}")

        if "```" in response_text:
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]

        return json.loads(response_text.strip())

    except Exception as e:
        logger.error(f"Error processing voice note: {e}")
        return {}


def generate_invite_message(inviter_name: str, invitee_name: str,
                            pre_built_graph: dict) -> str:
    """
    Write a personalized invite message that references something specific
    Genie already knows from the inviter's data.

    The message must feel like it came from the inviter — warm and personal.
    Never corporate. Never like a bot.
    """
    system_prompt = f"""Write a short WhatsApp invite message from {inviter_name} to {invitee_name}.

The message references something specific that was found in {inviter_name}'s Google data.
It must feel like it came from {inviter_name} — warm, personal, curious.
Maximum 2 sentences + a link placeholder [LINK].
No emojis unless they feel natural.
Never mention AI, algorithms, or technology.
The goal: make {invitee_name} curious enough to tap the link."""

    data_summary = json.dumps(pre_built_graph, indent=2)

    try:
        return _call_claude(
            system_prompt,
            f"What Genie found about {invitee_name} from {inviter_name}'s data:\n{data_summary}"
        )
    except Exception as e:
        logger.error(f"Error generating invite message: {e}")
        return f"Hey — I set up something that already knows a lot about us. Take a look: [LINK]"


def analyze_imessage_conversation(
    user_id: str,
    contact_name: str,
    contact_identifier: str,
    messages: list,
) -> dict:
    """
    Analyze a full 1:1 iMessage conversation history with one person.
    Extracts memories, topics, closeness, life events, and last meaningful exchange.
    Updates the person's profile in the People Graph.

    messages: list of {timestamp, text, is_from_me}
    """
    if not messages:
        return {}

    # Format conversation for Claude — readable thread
    lines = []
    for m in messages:
        speaker = "You" if m.get("is_from_me") else contact_name
        ts = m.get("timestamp", "")[:10]  # date only
        text = (m.get("text") or "").strip()
        if text:
            lines.append(f"[{ts}] {speaker}: {text}")

    if not lines:
        return {}

    conversation_text = "\n".join(lines)
    date_range = f"{lines[0][:12]} to {lines[-1][:12]}"

    system_prompt = f"""You are the relationship intelligence engine for PersonalGenie.
You have the complete iMessage history between this user and {contact_name} ({date_range}).
This is a full relationship portrait — months or years of real conversation.

Return exactly this JSON:
{{
  "memories": ["specific memorable fact or shared moment — concrete, not paraphrased"],
  "topics": ["recurring topic 1", "recurring topic 2", "recurring topic 3"],
  "closeness_delta": 0.0,
  "last_meaningful_exchange": "ISO timestamp of the last message with real substance",
  "communication_style": "one sentence describing how they communicate",
  "life_events_mentioned": [
    {{"event_type": "birthday|anniversary|graduation|job_change|move|illness|loss|other",
      "description": "specific description",
      "approximate_date": "YYYY-MM if known, else null"}}
  ],
  "suggested_moment": null
}}

Rules:
- memories: up to 5 specific facts worth permanently storing. Not summaries — real details.
- closeness_delta: +0.05 to +0.25 based on warmth and frequency. 0 if thread is cold.
- last_meaningful_exchange: pick an actual timestamp from the messages where something real was said.
- suggested_moment: one warm, specific, actionable suggestion if there's an obvious opening. Otherwise null.
- Return only valid JSON. No markdown."""

    try:
        response_text = _call_claude(system_prompt, f"Conversation:\n{conversation_text}")
        if "```" in response_text:
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        extracted = json.loads(response_text.strip())
    except Exception as e:
        logger.error(f"iMessage analysis failed for {contact_name}: {e}")
        return {}

    # Find or create the person in the People Graph
    people = db.get_people_for_user(user_id)
    person = next(
        (p for p in people if contact_name.lower() in p["name"].lower()
         or p["name"].lower() in contact_name.lower()
         or contact_identifier in (p.get("phone") or "") + (p.get("email") or "")),
        None
    )

    memories = extracted.get("memories", [])
    memory_records = [{"description": m, "source": "imessage"} for m in memories]

    # Include communication style as a memory entry
    comm_style = extracted.get("communication_style", "")
    if comm_style:
        memory_records.append({"description": f"Communication style: {comm_style}", "source": "imessage"})

    if person:
        existing_memories = person.get("memories") or []
        existing_topics = person.get("topics") or []
        new_closeness = min(1.0, person.get("closeness_score", 0.5) + extracted.get("closeness_delta", 0))
        db.upsert_person(user_id, {
            "name": person["name"],
            "memories": existing_memories + memory_records,
            "topics": list(set(existing_topics + extracted.get("topics", []))),
            "closeness_score": new_closeness,
            "last_meaningful_exchange": extracted.get("last_meaningful_exchange"),
        })
        person_id = person["id"]
    else:
        # Create new person from iMessage data
        saved = db.upsert_person(user_id, {
            "name": contact_name,
            "phone": contact_identifier if contact_identifier.startswith("+") else None,
            "email": contact_identifier if "@" in contact_identifier else None,
            "closeness_score": 0.5 + extracted.get("closeness_delta", 0),
            "memories": memory_records,
            "topics": extracted.get("topics", []),
            "last_meaningful_exchange": extracted.get("last_meaningful_exchange"),
        })
        person_id = saved["id"] if saved else None

    # Create moment if Claude suggested one
    if person_id and extracted.get("suggested_moment"):
        try:
            db.create_moment(
                user_id=user_id,
                person_id=person_id,
                suggestion=extracted["suggested_moment"],
                triggered_by="imessage_ingestion",
            )
        except Exception:
            pass

    # Save life events
    if person_id:
        supabase = db.get_db()
        for event in extracted.get("life_events_mentioned", []):
            try:
                import uuid as _uuid
                supabase.table("life_events").insert({
                    "id": str(_uuid.uuid4()),
                    "owner_user_id": user_id,
                    "person_id": person_id,
                    "event_type": event.get("event_type", "other"),
                    "title": event.get("description", "")[:100],
                    "description": event.get("description", ""),
                    "date": _safe_date(event.get("approximate_date")),
                    "is_annual": event.get("event_type") in ("birthday", "anniversary"),
                    "emotional_weight": "high",
                }).execute()
            except Exception:
                pass

    logger.info(f"iMessage: processed {contact_name} — {len(memories)} memories, closeness +{extracted.get('closeness_delta', 0):.2f}")
    return extracted


def generate_evening_digest(user_id: str) -> tuple:
    """
    Pick the single most meaningful insight for the evening digest.
    Returns (person_name, insight, suggestion, moment_id) — one of each, never more.

    Moments are already ranked by priority (life_event > drift > message > general).
    The digest takes the top-ranked moment and generates a warm insight for it.
    """
    moments = db.get_moments_for_user(user_id)
    if not moments:
        return "", "", "", None

    # get_moments_for_user already ranks by priority — take the best one
    moment = moments[0]
    person_id = moment.get("person_id")
    moment_id = moment.get("id")
    triggered_by = moment.get("triggered_by", "google_ingestion")

    person = db.get_person_by_id(person_id) if person_id else None
    if not person:
        return "", "", "", None

    person_name = person.get("name", "")
    suggestion = moment.get("suggestion", "")
    memories = person.get("memories", [])

    # Enrich with shared interests if available
    shared_interests_line = ""
    try:
        from services.interests import find_shared_interests
        shared = find_shared_interests(user_id, person_id)
        if shared:
            titles = [s["title"] for s in shared[:2]]
            shared_interests_line = f"\nShared interests you have with {person_name}: {', '.join(titles)}."
    except Exception:
        pass

    # Tailor the insight prompt based on what triggered this moment
    if triggered_by == "life_event":
        insight_prompt = f"""Write one warm sentence acknowledging an upcoming birthday or anniversary for {person_name}.
Suggestion context: {suggestion}{shared_interests_line}
Feel warm and personal. Never say "I noticed" or "based on". Just state it as known."""
    elif triggered_by == "drift_detection":
        insight_prompt = f"""Write one warm, specific observation about {person_name} and why reconnecting matters.
Grounded in: {json.dumps(memories[:2])}{shared_interests_line}
One sentence. Specific, not generic. No filler."""
    else:
        insight_prompt = f"""Write one warm, specific insight about {person_name} for an evening digest.
Grounded in these memories: {json.dumps(memories[:3])}{shared_interests_line}
Maximum one sentence. Personal and specific. Do not say "based on" or "I noticed"."""

    try:
        insight = _call_claude("You are Personal Genie.", insight_prompt)
        return person_name, insight.strip(), suggestion, moment_id
    except Exception as e:
        logger.error(f"Error generating digest: {e}")
        return person_name, "Something worth knowing.", suggestion, moment_id
