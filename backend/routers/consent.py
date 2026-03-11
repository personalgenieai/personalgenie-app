"""
routers/consent.py — Twilio webhook for incoming WhatsApp messages.

Handles:
- STOP → immediate full data deletion (under 5 seconds)
- YES / consent replies
- SHOW [name] → send person details
- IGNORE → dismiss the digest
- All other messages → forward to the WhatsApp conversation agent
"""
import logging
from typing import Optional
from fastapi import APIRouter, Form, Response, BackgroundTasks
from twilio.twiml.messaging_response import MessagingResponse
import database as db
from services.whatsapp import send_message
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/consent", tags=["consent"])


@router.post("/webhook")
async def twilio_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),                          # Twilio sends sender as "whatsapp:+1XXXXXXXXXX"
    Body: str = Form(default=""),                   # Message text (empty for pure voice notes)
    To: str = Form(...),                            # Our number
    NumMedia: str = Form(default="0"),              # Number of media attachments
    MediaUrl0: Optional[str] = Form(default=None),  # URL of first media file
    MediaContentType0: Optional[str] = Form(default=None),  # MIME type of first media
):
    """
    Twilio calls this endpoint for every incoming WhatsApp message.
    This is the entry point for all user replies.

    Plain English: whenever anyone messages Genie on WhatsApp, it comes here first.
    """
    # Strip the "whatsapp:" prefix to get a clean phone number
    phone = From.replace("whatsapp:", "").strip()
    message = Body.strip()

    logger.info(f"Incoming WhatsApp from {phone}: {message[:50]}")

    twiml = MessagingResponse()

    # ── STOP — hard delete, no questions asked ─────────────────────────────────
    if message.upper() in ("STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"):
        db.revoke_all_consent(phone)
        twiml.message(
            "Done. I've deleted everything I knew about you and I won't contact you again. "
            "If you ever want to start fresh, go to personalgenie.ai."
        )
        return Response(content=str(twiml), media_type="application/xml")

    # ── SHOW [name] — send person details from the digest ──────────────────────
    if message.upper().startswith("SHOW "):
        person_name = message[5:].strip().title()
        user = db.get_user_by_phone(phone)
        if user:
            people = db.get_people_for_user(user["id"])
            person = next((p for p in people if person_name.lower() in p["name"].lower()), None)
            if person:
                memories = person.get("memories", [])
                moments = person.get("suggested_moments", [])
                reply = f"*{person['name']}* — {person.get('relationship_type', '')}\n\n"
                if memories:
                    reply += f"📝 {memories[0].get('description', '')}\n\n"
                if moments:
                    reply += f"💡 {moments[0].get('suggestion', '')}"
                twiml.message(reply)
            else:
                twiml.message(f"I don't have much on {person_name} yet.")
        return Response(content=str(twiml), media_type="application/xml")

    # ── IGNORE — dismiss the digest, no response needed ────────────────────────
    if message.upper() == "IGNORE":
        return Response(content=str(twiml), media_type="application/xml")

    # ── Feedback commands ───────────────────────────────────────────────────────
    cmd = message.upper().strip()
    if cmd in ("GREAT", "DONE", "SKIP", "WRONG"):
        user = db.get_user_by_phone(phone)
        if user:
            moments = db.get_moments_for_user(user["id"])
            latest = moments[0] if moments else None
            if latest:
                if cmd in ("GREAT", "DONE"):
                    db.update_moment_status(latest["id"], "acted_on")
                    # Boost closeness score for this person slightly
                    if latest.get("person_id"):
                        person = db.get_person_by_id(latest["person_id"])
                        if person:
                            new_score = min(1.0, person.get("closeness_score", 0.5) + 0.02)
                            db.upsert_person(user["id"], {"name": person["name"], "closeness_score": new_score})
                    twiml.message("Glad that felt right. I'll remember what works for you.")
                elif cmd == "SKIP":
                    db.update_moment_status(latest["id"], "dismissed")
                    twiml.message("Noted. I'll adjust.")
                elif cmd == "WRONG":
                    db.update_moment_status(latest["id"], "dismissed")
                    # Log negative feedback
                    try:
                        import uuid
                        db.get_db().table("genie_feedback").insert({
                            "id": str(uuid.uuid4()),
                            "owner_user_id": user["id"],
                            "moment_id": latest["id"],
                            "feedback_type": "wrong_suggestion",
                            "original_content": latest.get("suggestion", ""),
                        }).execute()
                    except Exception:
                        pass
                    twiml.message("Got it — that was off. I'll recalibrate.")
        return Response(content=str(twiml), media_type="application/xml")

    # ── All other messages — route to active conversation or general agent ───────
    user = db.get_user_by_phone(phone)
    if user:
        # ── WhatsApp onboarding — intercept before normal routing ──────────────
        from services.onboarding import handle_onboarding_message, is_onboarding_complete
        if not is_onboarding_complete(user["id"]):
            reply = await handle_onboarding_message(user["id"], phone, message)
            if reply is not None:
                twiml.message(reply)
                return Response(content=str(twiml), media_type="application/xml")
        user_id = user["id"]

        # ── Voice note during an active training session ───────────────────────
        num_media = int(NumMedia or "0")
        if (
            num_media > 0
            and MediaUrl0
            and "audio" in (MediaContentType0 or "")
        ):
            from routers.messages import _health_session_active
            if _health_session_active.get(user_id, False):
                # Clear the waiting flag immediately so a second voice note
                # doesn't trigger another processing run
                _health_session_active[user_id] = False

                from services.training import process_session_voice_note
                background_tasks.add_task(
                    process_session_voice_note,
                    user_id=user_id,
                    phone=phone,
                    media_url=MediaUrl0,
                    media_content_type=MediaContentType0 or "audio/ogg",
                )
                # Acknowledge immediately — processing happens in background
                twiml.message("Got it, processing your session now...")
                return Response(content=str(twiml), media_type="application/xml")
            else:
                # Voice note arrived but no session is active — ignore media, treat
                # Body text (if any) as a normal message
                logger.info(f"Voice note from {phone} but no active session — ignoring media")

        # Persist the message so the 30-min batch can analyse it later
        if message:
            try:
                from datetime import datetime, timezone
                db.save_message(
                    user_id=user_id,
                    person_id=None,
                    platform="whatsapp",
                    body=message,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    sender_consented=user.get("whatsapp_consented", False),
                )
            except Exception as e:
                logger.warning(f"Could not save message for batch analysis: {e}")

        if not message:
            # Media-only message with no text and no active session — nothing to reply
            return Response(content=str(twiml), media_type="application/xml")

        # Check if there's an active Genie-initiated conversation to continue
        from services.genie_conversations import get_active_conversation, continue_conversation
        active_conv = get_active_conversation(user_id)
        if active_conv:
            # Route reply to the conversation — Genie extracts insight and responds
            insight = continue_conversation(user_id, message, phone)
            if insight:
                logger.info(f"Genie conversation continued for user {user_id}: {insight[:50]}")
            # twiml response is handled inside continue_conversation (sends directly)
        else:
            from routers.messages import handle_conversation
            reply = await handle_conversation(user_id, phone, message)
            twiml.message(reply)
    else:
        # Unknown number — they might have come here before registering
        twiml.message(
            "Hi! To get started, visit personalgenie.ai and enter your phone number."
        )

    return Response(content=str(twiml), media_type="application/xml")
