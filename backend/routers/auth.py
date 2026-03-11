"""
routers/auth.py — Auth endpoints:

1. POST /auth/start — web onboarding: phone → WhatsApp → Google OAuth
2. GET  /auth/connect/{user_id} — short redirect to full Google OAuth URL
3. GET  /auth/google/callback — Google OAuth callback
4. POST /auth/app/request-otp — iOS app: send 6-digit OTP via WhatsApp
5. POST /auth/app/verify-otp  — iOS app: verify OTP, return user_id + token
6. GET  /auth/app/me          — iOS app: fetch current user profile
"""
import base64
import hashlib
import hmac
import json
import random
import string
import time
import logging
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from google_auth_oauthlib.flow import Flow
import database as db
from services.whatsapp import send_welcome_message, send_first_magic_moment
from services.google_ingestion import run_full_ingestion
from services.intelligence import build_people_graph, get_first_magic_moment
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])

# Google OAuth scopes — one sign-in grants access to all three
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/photoslibrary.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
]


def _encode_state(user_id: str, phone: str, name: str) -> str:
    """
    Encode user context into the OAuth state parameter.
    Signed with jwt_secret so it can't be tampered with.
    This makes the auth flow completely stateless — survives restarts and multiple workers.
    """
    payload = base64.urlsafe_b64encode(
        json.dumps({"user_id": user_id, "phone": phone, "name": name}).encode()
    ).decode()
    sig = hmac.new(
        settings.jwt_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:16]
    return f"{sig}.{payload}"


def _decode_state(state: str) -> dict:
    """Verify and decode the state parameter. Raises ValueError if invalid."""
    try:
        sig, payload = state.split(".", 1)
    except ValueError:
        raise ValueError("Malformed state")
    expected = hmac.new(
        settings.jwt_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        raise ValueError("State signature invalid")
    return json.loads(base64.urlsafe_b64decode(payload).decode())


class StartRequest(BaseModel):
    phone: str   # phone number entered on personalgenie.ai
    name: str = ""


@router.post("/start")
async def start(body: StartRequest, background_tasks: BackgroundTasks):
    """
    Entry point: user enters phone number on personalgenie.ai.

    1. Creates (or finds) their user account
    2. Builds a Google OAuth URL
    3. Sends them a WhatsApp message with the link

    Plain English: this is what happens the moment someone types their
    number on the website and hits Enter.
    """
    phone = body.phone.strip()
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Phone number must include country code, e.g. +14155551234")

    # Create or find the user
    user = db.get_user_by_phone(phone)
    if not user:
        user = db.create_user(phone=phone, name=body.name)

    user_id = user["id"]

    # Send a short, clean link — the /auth/connect/{user_id} endpoint regenerates
    # the full OAuth URL on tap, so no long URL appears in the WhatsApp message
    connect_url = f"{settings.backend_url}/auth/connect/{user_id}"

    # Send WhatsApp welcome message with the short connect link
    background_tasks.add_task(
        send_welcome_message,
        phone=phone,
        name=body.name or "there",
        google_auth_url=connect_url,
    )

    return {"status": "message_sent", "user_id": user_id}


@router.get("/google/url")
async def google_auth_url(request: Request, user_id: str | None = None):
    """
    iOS app: returns the Google OAuth URL as JSON so the app can open it via Linking.
    Auth: X-App-Token header (authenticated flow) OR user_id query param (anonymous MVP flow).
    """
    token = request.headers.get("X-App-Token")
    if token:
        payload = verify_app_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        uid = payload["user_id"]
    elif user_id:
        uid = user_id
    else:
        raise HTTPException(status_code=401, detail="Missing X-App-Token or user_id")

    user = db.get_user_by_id(uid)
    phone = user.get("phone", "") if user else ""
    name = user.get("name", "") if user else ""

    encoded_state = _encode_state(uid, phone, name)
    flow = _build_google_flow()
    auth_url, _ = flow.authorization_url(
        state=encoded_state,
        access_type="offline",
        prompt="consent",
    )
    return {"auth_url": auth_url}


@router.get("/connect/{user_id}")
async def connect_google(user_id: str):
    """
    Short redirect link sent in WhatsApp. Generates the full Google OAuth URL
    on the fly and redirects — so users see a clean link, not 400 raw characters.

    personalgenie.ai/auth/connect/{user_id}  →  accounts.google.com/o/oauth2/...
    """
    from fastapi.responses import RedirectResponse
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Link not found. Please register at personalgenie.ai.")

    phone = user.get("phone", "")
    name = user.get("name", "")
    encoded_state = _encode_state(user_id, phone, name)
    flow = _build_google_flow()
    auth_url, _ = flow.authorization_url(
        state=encoded_state,
        access_type="offline",
        prompt="consent",
    )
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def google_callback(code: str, state: str, background_tasks: BackgroundTasks):
    """
    Google redirects here after the user signs in.

    1. Exchanges the auth code for access + refresh tokens
    2. Stores tokens in Supabase
    3. Kicks off background ingestion (Photos + Gmail + Contacts)
    4. Returns a page that tells the user to check WhatsApp

    The actual magic (People Graph + first moment) happens in the background
    and arrives via WhatsApp ~60 seconds later.
    """
    # Decode and verify the signed state to recover user context
    try:
        pending = _decode_state(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired auth state. Please start over.")

    user_id = pending["user_id"]
    phone = pending["phone"]
    user_name = pending.get("name", "")

    try:
        # Exchange code for tokens
        flow = _build_google_flow()
        flow.fetch_token(code=code)
        credentials = flow.credentials
        logger.info(f"Token granted scopes: {credentials.scopes}")

        # Store tokens in Supabase
        import google.oauth2.id_token
        import google.auth.transport.requests
        request = google.auth.transport.requests.Request()

        # Get Google user info
        id_info = google.oauth2.id_token.verify_oauth2_token(
            credentials.id_token,
            request,
            settings.google_client_id
        )
        google_id = id_info.get("sub", "")
        google_name = id_info.get("name", user_name)

        db.update_user_google(
            user_id=user_id,
            google_id=google_id,
            access_token=credentials.token,
            refresh_token=credentials.refresh_token or "",
        )

        # Update name if we now have it from Google
        if google_name and not user_name:
            db.get_db().table("users").update({"name": google_name}).eq("id", user_id).execute()

        # Kick off ingestion in background — don't make user wait
        background_tasks.add_task(
            _run_ingestion_and_notify,
            user_id=user_id,
            phone=phone,
            user_name=google_name or user_name,
            access_token=credentials.token,
            refresh_token=credentials.refresh_token or "",
        )

    except Exception as e:
        logger.error(f"Google OAuth error: {e}")
        raise HTTPException(status_code=500, detail="Google sign-in failed. Please try again.")

    # Return a simple page — the magic arrives via WhatsApp
    return _success_html(user_name or "there")


async def _run_ingestion_and_notify(
    user_id: str, phone: str, user_name: str,
    access_token: str, refresh_token: str
):
    """
    Background task: run full Google ingestion → build People Graph → send magic moment.
    This is what runs after Google OAuth completes.
    Takes ~30-60 seconds.
    """
    try:
        logger.info(f"Starting ingestion pipeline for user {user_id}")

        # Step 1: Fetch all Google data in parallel
        ingestion_data = await run_full_ingestion(user_id, access_token, refresh_token)

        # Step 2: Send to Claude → build People Graph → save to Supabase
        build_people_graph(user_id, ingestion_data)

        # Step 3: Extract life events from contacts and People Graph
        from services.life_events import extract_from_contacts, extract_life_events_for_user
        contacts = ingestion_data.get("contacts", {}).get("contacts", [])
        extract_from_contacts(user_id, contacts)
        extract_life_events_for_user(user_id)

        # Step 4: Generate and send the first magic moment via WhatsApp
        magic_moment = get_first_magic_moment(user_id, user_name)
        send_first_magic_moment(phone, magic_moment)

        logger.info(f"Ingestion pipeline complete for user {user_id}")

    except Exception as e:
        logger.error(f"Ingestion pipeline failed for user {user_id}: {e}")


# ── iOS app auth (OTP via WhatsApp) ──────────────────────────────────────────
# OTP store: phone → {code, expires_at}. In-memory for simplicity —
# survives single-worker deploys; TTL is 5 minutes.
_otp_store: dict = {}
OTP_TTL_SECONDS = 300


class AppOTPRequest(BaseModel):
    phone: str   # E.164 format, e.g. +14155551234


class AppOTPVerify(BaseModel):
    phone: str
    code: str


def _make_app_token(user_id: str) -> str:
    """
    Sign a simple token: HMAC-SHA256(user_id + timestamp) with jwt_secret.
    The app sends this as X-App-Token header; backend verifies it.
    """
    ts = str(int(time.time()))
    payload = f"{user_id}:{ts}"
    sig = hmac.new(
        settings.jwt_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{sig}"


def verify_app_token(token: str) -> str | None:
    """
    Verify an app token. Returns user_id on success, None on failure.
    Tokens expire after 30 days.
    """
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        user_id, ts, sig = parts
        expected = hmac.new(
            settings.jwt_secret.encode(),
            f"{user_id}:{ts}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(time.time()) - int(ts) > 30 * 24 * 3600:  # 30 days
            return None
        return {"user_id": user_id}
    except Exception:
        return None


@router.post("/app/request-otp")
async def app_request_otp(body: AppOTPRequest):
    """
    iOS app calls this when the user enters their phone number.
    Sends a 6-digit OTP via WhatsApp. The user must already have a Genie
    account (registered via personalgenie.ai). Returns 404 if unknown.
    """
    from services.whatsapp import send_message

    phone = body.phone.strip()
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Phone must include country code, e.g. +14155551234")

    user = db.get_user_by_phone(phone)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="No Genie account found for this number. Sign up at personalgenie.ai first."
        )

    code = "".join(random.choices(string.digits, k=6))
    _otp_store[phone] = {"code": code, "expires_at": time.time() + OTP_TTL_SECONDS}

    send_message(
        phone,
        f"Your Personal Genie app code: *{code}*\n\nExpires in 5 minutes. Don't share this.",
        user_id=user["id"],
    )
    logger.info(f"OTP sent to {phone[-4:]}****")
    return {"status": "sent"}


@router.post("/app/verify-otp")
async def app_verify_otp(body: AppOTPVerify):
    """
    Verify the OTP. On success returns user_id + a signed token the app
    stores in AsyncStorage and sends on every request as X-App-Token.
    """
    phone = body.phone.strip()
    entry = _otp_store.get(phone)

    if not entry or entry["code"] != body.code.strip():
        raise HTTPException(status_code=401, detail="Invalid or expired code.")
    if time.time() > entry["expires_at"]:
        _otp_store.pop(phone, None)
        raise HTTPException(status_code=401, detail="Code expired. Request a new one.")

    _otp_store.pop(phone, None)  # One-time use

    user = db.get_user_by_phone(phone)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    token = _make_app_token(user["id"])
    return {
        "user_id": user["id"],
        "name": user.get("name", ""),
        "token": token,
    }


@router.get("/app/me")
async def app_me(x_app_token: str | None = None):
    """
    Return the current user's profile. Used by the app on startup
    to confirm the stored token is still valid.
    """
    from fastapi import Header
    if not x_app_token:
        raise HTTPException(status_code=401, detail="Missing X-App-Token header")
    user_id = verify_app_token(x_app_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user["id"],
        "name": user.get("name", ""),
        "phone": user.get("phone", ""),
        "whatsapp_consented": user.get("whatsapp_consented", False),
    }


def _build_google_flow() -> Flow:
    """Build a Google OAuth flow object with our credentials and scopes."""
    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=GOOGLE_SCOPES,
        redirect_uri=settings.google_redirect_uri,
    )


def _success_html(name: str):
    """
    Simple HTML page shown after Google sign-in.
    Tells the user to check WhatsApp — the magic is on its way.
    """
    from fastapi.responses import HTMLResponse
    first_name = name.split()[0] if name else "there"
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Personal Genie</title>
  <style>
    body {{ margin: 0; background: #0a0a0a; color: #fff; font-family: -apple-system, sans-serif;
           display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
    .card {{ text-align: center; padding: 40px 24px; max-width: 380px; }}
    .orb {{ font-size: 64px; margin-bottom: 24px; }}
    h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 12px; }}
    p {{ color: #888; font-size: 16px; line-height: 1.6; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="orb">🔮</div>
    <h1>Your Genie is awake, {first_name}.</h1>
    <p>It's learning what matters in your life right now.<br><br>
       Check WhatsApp in about a minute — it has something to tell you.</p>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)
