"""
routers/invites.py — Invite flow.

POST /invites/send — Leo picks someone from his People Graph.
  Genie generates a personalized invite message.
  Sends it via WhatsApp with a unique link.

GET /invites/{token} — Invitee taps the link.
  Shows a consent + Google sign-in page.
  When they sign in, their own Genie is born.
"""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import database as db
from services.whatsapp import send_invite, send_bilateral_notification
from services.intelligence import generate_invite_message
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/invites", tags=["invites"])


class InviteRequest(BaseModel):
    user_id: str      # Leo's user ID
    person_id: str    # the person record Leo wants to invite


@router.post("/send")
async def send_invite_to_person(body: InviteRequest):
    """
    Leo taps 'Invite' on a person in his People Graph.

    1. Get what Genie knows about that person from Leo's data
    2. Claude writes a personal invite message
    3. Send it via WhatsApp with a unique link
    4. Save invite record in Supabase
    """
    user = db.get_user_by_id(body.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    person = db.get_person_by_id(body.person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    if not person.get("phone"):
        raise HTTPException(status_code=400, detail="No phone number for this person")

    inviter_name = user.get("name", "Someone")
    invitee_name = person.get("name", "")
    invitee_phone = person.get("phone", "")

    # Build the pre-graph — what Genie already knows about the invitee
    pre_built_graph = {
        "name": invitee_name,
        "relationship_type": person.get("relationship_type", ""),
        "memories": person.get("memories", [])[:3],
        "topics": person.get("topics", []),
        "closeness_score": person.get("closeness_score", 0.5),
    }

    # Create invite record with unique token
    invite = db.create_invite(
        inviter_user_id=body.user_id,
        invitee_phone=invitee_phone,
        invitee_name=invitee_name,
        pre_built_graph=pre_built_graph,
    )

    token = invite["invite_token"]
    invite_link = f"{settings.backend_url}/invites/{token}"

    # Generate the personal hook — what specific thing should the message reference?
    memories = person.get("memories", [])
    personal_hook = ""
    if memories:
        # Find the most compelling memory to reference
        personal_hook = memories[0].get("description", "")

    # Claude writes the invite message in Leo's voice
    claude_message = generate_invite_message(
        inviter_name=inviter_name,
        invitee_name=invitee_name,
        pre_built_graph=pre_built_graph,
    )

    # Replace [LINK] placeholder with actual link
    final_message = claude_message.replace("[LINK]", invite_link)
    if invite_link not in final_message:
        final_message += f"\n\n{invite_link}"

    # Send via WhatsApp
    send_invite(
        to_phone=invitee_phone,
        inviter_name=inviter_name,
        personal_hook=personal_hook,
        invite_link=invite_link,
    )

    logger.info(f"Invite sent to {invitee_name} ({invitee_phone}) from {inviter_name}")

    return {
        "status": "sent",
        "invite_token": token,
        "invite_link": invite_link,
        "message_preview": final_message[:100],
    }


@router.get("/{token}")
async def view_invite(token: str):
    """
    Invitee taps the link in their WhatsApp message.
    Shows them a consent page with a Google sign-in button.

    This is the moment their own Genie is born.
    """
    invite = db.get_invite_by_token(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found or expired")

    if invite.get("status") == "accepted":
        return HTMLResponse(_already_joined_html(invite.get("invitee_name", "there")))

    # Get what Genie already knows from the inviter's data
    pre_graph = invite.get("pre_built_graph", {})
    invitee_name = invite.get("invitee_name", "there")
    inviter_user_id = invite.get("inviter_user_id", "")
    inviter = db.get_user_by_id(inviter_user_id)
    inviter_name = inviter.get("name", "Someone") if inviter else "Someone"

    # Build a teaser — something specific from the pre-built graph
    memories = pre_graph.get("memories", [])
    teaser = ""
    if memories:
        teaser = memories[0].get("description", "")

    # Google OAuth URL that will start their own Genie
    google_start_url = (
        f"{settings.backend_url}/auth/start-invite?"
        f"token={token}&phone={invite.get('invitee_phone', '')}"
    )

    return HTMLResponse(_consent_page_html(
        invitee_name=invitee_name,
        inviter_name=inviter_name,
        teaser=teaser,
        google_start_url=google_start_url,
        token=token,
    ))


def _consent_page_html(invitee_name: str, inviter_name: str,
                        teaser: str, google_start_url: str, token: str) -> str:
    """
    The consent + Google sign-in page invitees see when they tap the link.
    Mobile-first design. One clear action. No friction.
    """
    first_name = invitee_name.split()[0] if invitee_name else "there"
    inviter_first = inviter_name.split()[0] if inviter_name else "them"

    teaser_html = f'<p class="teaser">"{teaser}"</p>' if teaser else ""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Personal Genie</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0a0a0a; color: #fff; font-family: -apple-system, sans-serif;
           min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }}
    .card {{ max-width: 380px; width: 100%; text-align: center; }}
    .orb {{ font-size: 56px; margin-bottom: 20px; }}
    h1 {{ font-size: 26px; font-weight: 700; margin-bottom: 12px; line-height: 1.3; }}
    .subtitle {{ color: #888; font-size: 15px; line-height: 1.6; margin-bottom: 20px; }}
    .teaser {{ background: #1a1a1a; border-left: 3px solid #9b59b6; padding: 14px 16px;
               border-radius: 8px; font-size: 14px; color: #ccc; text-align: left;
               margin-bottom: 24px; line-height: 1.5; font-style: italic; }}
    .consent-box {{ background: #111; border-radius: 12px; padding: 16px;
                    margin-bottom: 24px; text-align: left; }}
    .consent-box p {{ font-size: 13px; color: #777; margin-bottom: 8px; }}
    .consent-box ul {{ font-size: 13px; color: #666; padding-left: 16px; }}
    .consent-box li {{ margin-bottom: 4px; }}
    .btn {{ display: block; background: #fff; color: #000; font-size: 16px; font-weight: 600;
            padding: 16px; border-radius: 14px; text-decoration: none; margin-bottom: 12px; }}
    .skip {{ color: #555; font-size: 13px; }}
    .skip a {{ color: #777; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="orb">🔮</div>
    <h1>Hi {first_name} — {inviter_first} found something.</h1>
    <p class="subtitle">Their Genie already knows something about your connection.<br>
    Here's what it found:</p>
    {teaser_html}
    <div class="consent-box">
      <p>To see the full picture and let your Genie learn your world:</p>
      <ul>
        <li>✓ See what Genie already knows about you</li>
        <li>✓ Connect Google to share your side of the story</li>
        <li>✓ Your own relationship graph, built in 60 seconds</li>
      </ul>
    </div>
    <a class="btn" href="{google_start_url}">Connect Google & Meet Your Genie →</a>
    <p class="skip">Your data is yours. Reply STOP to Genie's WhatsApp at any time and everything is deleted instantly.</p>
  </div>
</body>
</html>"""


def _already_joined_html(name: str) -> str:
    first_name = name.split()[0] if name else "there"
    return f"""<!DOCTYPE html>
<html>
<head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Personal Genie</title>
<style>body{{background:#0a0a0a;color:#fff;font-family:-apple-system,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:24px;}}
.orb{{font-size:56px;margin-bottom:20px;}}h1{{font-size:24px;}}p{{color:#888;margin-top:12px;}}</style>
</head><body>
<div><div class="orb">🔮</div>
<h1>You're already in, {first_name}.</h1>
<p>Check your WhatsApp — your Genie is there.</p></div>
</body></html>"""
