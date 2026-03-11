"""
services/whatsapp.py — Twilio WhatsApp wrapper.
All Twilio calls go through here. Nothing else imports twilio directly.
Every outbound message is logged to the notifications table for the Transparency tab.
"""
import uuid
import logging
from twilio.rest import Client
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _client() -> Client:
    """Return a configured Twilio client."""
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def _format_number(phone: str) -> str:
    """
    Ensure phone number is in Twilio WhatsApp format.
    Twilio requires "whatsapp:+1XXXXXXXXXX" format.
    """
    phone = phone.strip()
    if not phone.startswith("whatsapp:"):
        phone = f"whatsapp:{phone}"
    return phone


def send_message(to_phone: str, message: str, user_id: str = None, moment_id: str = None) -> str:
    """
    Send a WhatsApp message to a phone number.
    Logs every send to the notifications table for the Transparency tab.
    Returns the Twilio message SID for tracking.
    """
    client = _client()
    msg = client.messages.create(
        from_=settings.twilio_whatsapp_number,
        to=_format_number(to_phone),
        body=message,
    )
    # Log to notifications table (non-blocking — never fail the send if logging fails)
    if user_id:
        try:
            import database as db
            db.get_db().table("notifications").insert({
                "id": str(uuid.uuid4()),
                "owner_user_id": user_id,
                "moment_id": moment_id,
                "channel": "whatsapp",
                "content": message[:500],  # truncate very long messages
                "status": "sent",
                "sent_at": "now()",
            }).execute()
        except Exception as e:
            logger.warning(f"Could not log notification for user {user_id}: {e}")
    return msg.sid


def send_welcome_message(phone: str, name: str, google_auth_url: str) -> str:
    """
    Send the first message when someone registers on personalgenie.ai.
    This message welcomes them, asks them to save the contact,
    and gives them the Google auth link to unlock their People Graph.
    """
    first_name = name.split()[0] if name else "there"
    message = (
        f"Hi {first_name} 👋 Your Personal Genie is awake.\n\n"
        f"Save this number as *Personal Genie* — I'll feel more like me when I reach out.\n\n"
        f"To learn what matters in your life, connect your Google account. "
        f"I'll quietly look through your Photos, Gmail and Contacts and come back with something that surprises you:\n\n"
        f"{google_auth_url}\n\n"
        f"Reply *STOP* at any time and I'll forget everything instantly. 🔮"
    )
    return send_message(phone, message)


def send_first_magic_moment(phone: str, moment_text: str) -> str:
    """
    Send the first insight after Google ingestion completes.
    This is the moment that makes the product feel magical.
    """
    return send_message(phone, moment_text)


def send_invite(to_phone: str, inviter_name: str, personal_hook: str, invite_link: str) -> str:
    """
    Send a personalized invite to someone who isn't on PersonalGenie yet.
    personal_hook is something specific Genie found — e.g. "47 photos going back to 2015".
    """
    message = (
        f"Hi — {inviter_name} set up something that already found {personal_hook}. "
        f"Takes 30 seconds to see what it knows:\n\n"
        f"{invite_link}"
    )
    return send_message(to_phone, message)


def send_evening_digest(phone: str, person_name: str, insight: str, suggestion: str) -> str:
    """
    Send the 7pm daily digest message.
    One person, one insight, one suggestion. Never more.
    """
    message = (
        f"Here's what your Genie noticed today ✨\n\n"
        f"*{person_name}* — {insight}\n\n"
        f"💡 {suggestion}\n\n"
        f"Reply *SHOW {person_name.upper()}* to see more or *IGNORE* to dismiss"
    )
    return send_message(phone, message)


def send_voice_note_confirmation(phone: str, person_name: str) -> str:
    """Send confirmation after a voice note is processed."""
    return send_message(phone, f"Got it — I'll remember that about {person_name} 🧠")


def send_bilateral_notification(phone: str, joined_name: str) -> str:
    """Notify Leo when someone he invited joins PersonalGenie."""
    return send_message(
        phone,
        f"{joined_name} just joined — your relationship graph just got a lot richer ✨"
    )
