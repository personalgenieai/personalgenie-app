"""
config.py — All environment variables in one place.
Never import os.environ directly anywhere else — always use settings from here.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Twilio WhatsApp ────────────────────────────────────────────────────────
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_number: str          # e.g. "whatsapp:+14155238886"

    # ── Supabase ───────────────────────────────────────────────────────────────
    supabase_url: str
    supabase_key: str                    # service_role key — never the anon key

    # ── AI APIs ────────────────────────────────────────────────────────────────
    anthropic_api_key: str
    openai_api_key: str

    # ── Google OAuth ───────────────────────────────────────────────────────────
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str             # e.g. "https://your-railway-url/auth/google/callback"

    # ── App ────────────────────────────────────────────────────────────────────
    backend_url: str                     # Railway URL (or ngrok URL for local dev)
    jwt_secret: str                      # random string: openssl rand -hex 32
    leo_phone_number: str                # e.g. "+14155551234" — used for digest

    # ── Spotify OAuth ──────────────────────────────────────────────────────────
    spotify_client_id: str = ""              # from Spotify Developer Dashboard
    spotify_client_secret: str = ""          # only needed for server-side refresh

    # ── Plaid Financial ────────────────────────────────────────────────────────
    plaid_client_id: str = ""                # from Plaid Dashboard
    plaid_secret: str = ""                   # Plaid secret key
    plaid_env: str = "sandbox"               # "sandbox" | "production"

    # ── Claude model ───────────────────────────────────────────────────────────
    claude_model: str = "claude-sonnet-4-5"

    # ── APNs Push Notifications ────────────────────────────────────────────────
    apns_key_id: str = ""          # 10-char key ID from Apple Developer
    apns_team_id: str = ""         # 10-char team ID
    apns_bundle_id: str = ""       # com.yourcompany.personalgenie
    apns_auth_key: str = ""        # contents of .p8 file (base64 or raw PEM)
    apns_sandbox: bool = True      # False = production APNs

    # ── Stripe Billing ─────────────────────────────────────────────────────────
    stripe_secret_key: str = ""           # sk_live_... or sk_test_...
    stripe_webhook_secret: str = ""       # whsec_...
    stripe_price_individual: str = ""     # price_... from Stripe Dashboard
    stripe_price_family: str = ""
    stripe_price_pro: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings — only reads .env once per process."""
    return Settings()
