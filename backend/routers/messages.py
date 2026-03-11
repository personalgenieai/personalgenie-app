"""
routers/messages.py — WhatsApp conversation agent.

When a user sends a message to Genie, Claude responds in context —
knowing their People Graph, recent moments, the last thing Genie sent,
and full conversation history.

Also runs the 30-minute batch processor that analyzes new messages
and updates the People Graph.
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel
from anthropic import Anthropic
import database as db
from services.intelligence import analyze_messages, analyze_imessage_conversation
from services.nutrition import (
    is_food_intent,
    is_session_trigger,
    parse_food_input,
    store_food_log,
    get_daily_summary,
    get_days_logging,
    build_acknowledgment,
)
from fastapi import HTTPException
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/messages", tags=["messages"])

_anthropic = Anthropic(api_key=settings.anthropic_api_key)

# In-memory conversation history per user — last 20 turns
# Also tracks the last moment Genie surfaced so replies are contextual
_conversation_history: dict = {}    # user_id -> list of {role, content}
_last_moment_sent: dict = {}         # user_id -> {person_name, suggestion, triggered_by}
_health_session_active: dict = {}    # user_id -> bool — True when awaiting training session voice note


def set_health_session_active(user_id: str, active: bool) -> None:
    """Called by health router when user triggers 'starting session'."""
    _health_session_active[user_id] = active


def set_last_moment(user_id: str, person_name: str, suggestion: str, triggered_by: str):
    """
    Called by the digest sender after Genie sends a moment via WhatsApp.
    Stores it so the next conversation turn knows what was just surfaced.
    """
    _last_moment_sent[user_id] = {
        "person_name": person_name,
        "suggestion": suggestion,
        "triggered_by": triggered_by,
    }


async def handle_conversation(user_id: str, phone: str, user_message: str) -> str:
    """
    Handle an incoming WhatsApp message and generate Genie's reply.

    Routing order (checked before the main Claude conversation):
    1. Learning question answer — if Genie is waiting for a reply, capture it
    2. Session trigger ("starting session") → start training session flow
    3. Food intent detected → log food, optionally append learning question
    4. Anything else → relationship conversation agent (Claude)

    Genie knows:
    - The user's top people, closeness scores, and memories
    - The moment Genie most recently sent (so replies like "tell me more" make sense)
    - What triggered that moment (birthday / drift / message signal)
    - Full conversation history (last 20 turns)
    """
    # ── Health routing: check before any Claude call ──────────────────────────

    # 1. Learning question answer — must be checked first so the reply isn't
    #    misrouted to the food logger or relationship agent
    try:
        from services.habit import is_awaiting_answer, handle_question_answer
        if is_awaiting_answer(user_id):
            ack = handle_question_answer(user_id, user_message)
            if ack:
                return ack
    except Exception as e:
        logger.error(f"Learning question answer handling failed for {user_id}: {e}")

    if is_session_trigger(user_message):
        # User is starting a training session — set waiting state and reply
        _health_session_active[user_id] = True
        return "I'm listening. Send me a voice note when you're done and I'll put together a summary."

    if is_food_intent(user_message):
        try:
            tz_offset = 0
            parsed = parse_food_input(user_message, "text")
            daily = store_food_log(user_id, user_message, parsed, "text", tz_offset)
            days = get_days_logging(user_id)
            ack = build_acknowledgment(parsed, daily, days)

            # Ensure health profile exists so learning questions have a row to update
            from services.habit import (
                ensure_health_profile_exists,
                get_next_question,
                mark_question_asked,
            )
            ensure_health_profile_exists(user_id)
            q = get_next_question(user_id)
            if q:
                idx, question_text = q
                mark_question_asked(user_id, idx)
                if ack:
                    return f"{ack}\n\n{question_text}"
                return question_text

            if ack:
                return ack
            # Logged silently — fall through so the relationship agent can reply
            # if the message had dual intent
        except Exception as e:
            logger.error(f"Food logging failed for user {user_id}: {e}")
            return "Logged. Give me a moment if anything looked off."

    # ── Relationship conversation agent ──────────────────────────────────────
    from services.emotional_state import get_tone_modifier
    from services.interests import extract_from_message
    import asyncio

    user = db.get_user_by_id(user_id)
    user_name = user.get("name", "there") if user else "there"

    # ── World Model assembly (replaces manual people/moments context build) ──
    world_model_context = ""
    try:
        from core.world_model import assemble_world_model
        wm = await assemble_world_model(user_id)
        world_model_context = wm.to_claude_context()
    except Exception as _wm_err:
        logger.warning("World Model assembly failed, falling back to basic context: %s", _wm_err)
        # Fallback: build basic context manually
        people = db.get_people_for_user(user_id)
        moments = db.get_moments_for_user(user_id)
        people_lines = []
        for p in people[:10]:
            memories = p.get("memories", [])
            top_memory = memories[0].get("description", "") if memories else ""
            line = f"- {p['name']} ({p.get('relationship_type', '')}): closeness {p.get('closeness_score', 0.5):.1f}"
            if top_memory:
                line += f" | {top_memory[:80]}"
            people_lines.append(line)
        world_model_context = "Relationships:\n" + ("\n".join(people_lines) or "Still learning...")

    # ── Extract third-party signals from this message (fire-and-forget) ──────
    try:
        from services.signal_extractor import extract_signals_from_message
        # participants = just this user (we're extracting signals about third parties)
        asyncio.create_task(
            extract_signals_from_message(
                source_user_id=user_id,
                message_text=user_message,
                participants=[user_name],
            )
        )
    except Exception:
        pass

    # Extract interests from this message (non-blocking)
    try:
        extract_from_message(user_id, user_message)
    except Exception:
        pass

    tone_modifier = get_tone_modifier(user_id)

    # What Genie most recently surfaced — this is the active conversational context
    last_moment = _last_moment_sent.get(user_id)
    if last_moment:
        trigger_label = {
            "life_event": "an upcoming birthday or anniversary",
            "drift_detection": "a relationship that's been quiet",
            "message_analysis": "something in their recent messages",
            "voice_note": "a voice note they recorded",
            "google_ingestion": "their relationship history",
        }.get(last_moment["triggered_by"], "something Genie noticed")

        moment_context = (
            f"The last thing you surfaced to {user_name} was about "
            f"*{last_moment['person_name']}*, triggered by {trigger_label}:\n"
            f"\"{last_moment['suggestion']}\"\n\n"
            f"If they ask to elaborate, tell me more, or ask about this person — "
            f"this is what they're referring to."
        )
    else:
        moments = db.get_moments_for_user(user_id)
        top_moment = moments[0] if moments else None
        if top_moment:
            person_data = top_moment.get("people") or {}
            pname = person_data.get("name", "someone") if isinstance(person_data, dict) else "someone"
            moment_context = (
                f"Your current top suggestion for {user_name} is about {pname}:\n"
                f"\"{top_moment.get('suggestion', '')}\""
            )
        else:
            moment_context = "No active suggestions yet — still building the picture."

    system_prompt = f"""You are Personal Genie — a wise, warm presence for {user_name}.

{world_model_context}

Active context — what you most recently told them:
{moment_context}

Rules:
- Warm and personal. Like a wise friend who pays attention, not a tech product.
- Never say "based on your data", "I noticed from", or "according to". Just know things.
- Never reveal sources — not what people said about each other, not where you learned anything.
- If cross-user signals suggest someone needs care, be attentive in your own voice — never attribute.
- Keep replies to 2-4 sentences. Never more.
- If they ask about someone, draw on everything you know about that person specifically.
- If they're responding to the moment you surfaced, stay in that thread — don't change subjects.
- One gentle question per reply, maximum. Never fire multiple questions.
- Reply GREAT, SKIP, DONE, or WRONG to any suggestion — Genie will remember.
{tone_modifier}"""

    if user_id not in _conversation_history:
        _conversation_history[user_id] = []

    history = _conversation_history[user_id]
    history.append({"role": "user", "content": user_message})

    if len(history) > 20:
        history = history[-20:]

    try:
        response = _anthropic.messages.create(
            model=settings.claude_model,
            max_tokens=300,
            system=system_prompt,
            messages=history,
        )
        reply = response.content[0].text

        history.append({"role": "assistant", "content": reply})
        _conversation_history[user_id] = history

        return reply

    except Exception as e:
        logger.error(f"Conversation error for user {user_id}: {e}")
        return "I'm here. Give me a moment and try again."


# ── iMessage import ───────────────────────────────────────────────────────────

class IMessageEntry(BaseModel):
    timestamp: str          # ISO-8601
    text: str
    is_from_me: bool


class IMessageConversation(BaseModel):
    contact_name: str
    contact_identifier: str  # phone or email as stored in chat.db
    messages: List[IMessageEntry]


class IMessageImportRequest(BaseModel):
    user_id: str
    conversations: List[IMessageConversation]


@router.post("/import/imessage")
async def import_imessage(payload: IMessageImportRequest, background_tasks: BackgroundTasks):
    """
    Receive iMessage conversations exported from the local Mac script and
    analyze each one in the background to enrich the People Graph.

    The Mac script (tools/imessage_export.py) reads ~/Library/Messages/chat.db,
    resolves contact names via Contacts.app, and POSTs here.
    """
    # Kick off analysis for each conversation — non-blocking
    background_tasks.add_task(
        _process_imessage_import,
        user_id=payload.user_id,
        conversations=[c.dict() for c in payload.conversations],
    )
    return {
        "status": "queued",
        "conversations": len(payload.conversations),
        "user_id": payload.user_id,
    }


async def _process_imessage_import(user_id: str, conversations: list) -> None:
    """
    Background task: run Claude analysis on each iMessage conversation.
    Runs sequentially to avoid hammering the Anthropic API.
    """
    import asyncio

    results = []
    for conv in conversations:
        try:
            result = analyze_imessage_conversation(
                user_id=user_id,
                contact_name=conv["contact_name"],
                contact_identifier=conv["contact_identifier"],
                messages=conv["messages"],
            )
            results.append({"contact": conv["contact_name"], "status": "ok", **result})
        except Exception as e:
            logger.error(f"iMessage analysis failed for {conv['contact_name']}: {e}")
            results.append({"contact": conv["contact_name"], "status": "error", "error": str(e)})

        # Small pause between Claude calls to stay within rate limits
        await asyncio.sleep(1)

    logger.info(
        f"iMessage import complete for user {user_id}: "
        f"{sum(1 for r in results if r['status'] == 'ok')}/{len(results)} conversations analysed"
    )


class IosChatRequest(BaseModel):
    user_id: str
    message: str


@router.post("/ios-chat")
async def ios_chat(body: IosChatRequest, request: Request):
    """
    iOS Chat tab → Genie conversation.
    Authenticated via X-App-Token header.
    Returns {reply: str}.
    """
    from routers.auth import verify_app_token
    token = request.headers.get("X-App-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-App-Token")
    payload = verify_app_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.get_user_by_id(body.user_id)
    phone = user.get("phone", "") if user else ""

    reply = await handle_conversation(body.user_id, phone, body.message)
    return {"reply": reply}


@router.post("/process-batch")
async def process_message_batch(user_id: str):
    """
    Process unprocessed messages for a user.
    Called by the scheduler every 30 minutes.
    """
    messages = db.get_unprocessed_messages(user_id, limit=50)
    if not messages:
        return {"status": "no_messages"}

    extracted = analyze_messages(user_id, messages)
    db.mark_messages_processed([m["id"] for m in messages])

    return {"status": "processed", "count": len(messages), "extracted": extracted}
