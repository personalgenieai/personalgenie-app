"""
Spotify OAuth router.

Endpoints:
  GET  /spotify/connect          — build authorization URL (PKCE)
  GET  /spotify/callback         — exchange code for tokens, save to DB
  POST /spotify/disconnect       — revoke and delete tokens
  GET  /spotify/status           — check connection status
  GET  /spotify/devices          — list available Spotify Connect devices
  POST /spotify/play             — play music on a device
  PUT  /spotify/pause            — pause playback
  PUT  /spotify/resume           — resume playback
  PUT  /spotify/volume           — set volume
  GET  /spotify/now-playing      — currently playing track
"""
import base64
import hashlib
import os
import time
import logging

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from config import get_settings
from services.spotify_client import SpotifyClient, REQUIRED_SCOPES, SPOTIFY_ACCOUNTS
from routers.auth import verify_app_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/spotify", tags=["spotify"])

# In-memory PKCE verifier store (keyed by state, TTL ~10min)
_pkce_store: dict[str, dict] = {}


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str, str]:
    """Returns (code_verifier, code_challenge, state)."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    state = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
    return verifier, challenge, state


# ── Pydantic models ───────────────────────────────────────────────────────────

class PlayRequest(BaseModel):
    query: str | None = None
    uri: str | None = None
    device_name: str | None = None
    volume: int | None = None


class VolumeRequest(BaseModel):
    percent: int   # 0–100


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_user_id(request: Request) -> str:
    token = request.headers.get("X-App-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-App-Token")
    payload = verify_app_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]


# ── Connect ───────────────────────────────────────────────────────────────────

@router.get("/connect")
async def spotify_connect(request: Request):
    """Return the Spotify authorization URL. Client opens this in a browser."""
    user_id = _get_user_id(request)
    settings = get_settings()

    verifier, challenge, state = _generate_pkce()
    _pkce_store[state] = {
        "verifier": verifier,
        "user_id": user_id,
        "created_at": time.time(),
    }

    # Clean up stale entries
    now = time.time()
    for k in list(_pkce_store.keys()):
        if now - _pkce_store[k]["created_at"] > 600:
            del _pkce_store[k]

    redirect_uri = f"{settings.backend_url}/spotify/callback"
    params = (
        f"client_id={settings.spotify_client_id}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&scope={REQUIRED_SCOPES.replace(' ', '%20')}"
        f"&state={state}"
        f"&code_challenge_method=S256"
        f"&code_challenge={challenge}"
    )
    return {"auth_url": f"{SPOTIFY_ACCOUNTS}/authorize?{params}"}


@router.get("/callback")
async def spotify_callback(
    code: str = Query(...),
    state: str = Query(...),
    error: str | None = Query(None),
):
    """Spotify redirects here after the user grants access."""
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify auth error: {error}")

    entry = _pkce_store.pop(state, None)
    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter")

    user_id = entry["user_id"]
    verifier = entry["verifier"]
    settings = get_settings()
    redirect_uri = f"{settings.backend_url}/spotify/callback"

    try:
        token_data = await SpotifyClient.exchange_code(code, verifier, redirect_uri)
    except Exception as exc:
        logger.error("Spotify code exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail="Spotify token exchange failed")

    # Fetch Spotify user profile to get display name
    client = SpotifyClient(user_id)
    client._access_token = token_data["access_token"]
    client._refresh_token = token_data.get("refresh_token", "")
    client._token_expires_at = time.time() + token_data.get("expires_in", 3600)

    try:
        profile = await client._api("GET", "/me")
        spotify_user_id = profile.get("id", "")
        display_name = profile.get("display_name", "")
    except Exception:
        spotify_user_id = ""
        display_name = ""

    # Save to DB
    try:
        from db import get_db
        db = get_db()
        db.table("music_connections").upsert({
            "user_id": user_id,
            "provider": "spotify",
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", ""),
            "token_expires_at": client._token_expires_at,
            "scopes": REQUIRED_SCOPES,
            "provider_user_id": spotify_user_id,
            "display_name": display_name,
        }).execute()
    except Exception as exc:
        logger.error("Could not save Spotify connection for %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Could not save connection")

    # Redirect to app deep-link or success page
    return RedirectResponse(url=f"{settings.backend_url}/spotify/connected")


@router.get("/connected")
async def spotify_connected():
    return {"status": "connected", "message": "Spotify connected. You can close this window."}


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def spotify_status(request: Request):
    user_id = _get_user_id(request)
    try:
        from db import get_db
        db = get_db()
        row = (
            db.table("music_connections")
            .select("display_name, token_expires_at, scopes")
            .eq("user_id", user_id)
            .eq("provider", "spotify")
            .single()
            .execute()
        )
        if row.data:
            return {
                "connected": True,
                "display_name": row.data.get("display_name"),
                "scopes": row.data.get("scopes"),
            }
    except Exception:
        pass
    return {"connected": False}


# ── Disconnect ────────────────────────────────────────────────────────────────

@router.post("/disconnect")
async def spotify_disconnect(request: Request):
    user_id = _get_user_id(request)
    try:
        from db import get_db
        db = get_db()
        db.table("music_connections").delete().eq("user_id", user_id).eq("provider", "spotify").execute()
    except Exception as exc:
        logger.warning("Could not delete Spotify connection for %s: %s", user_id, exc)
    return {"status": "disconnected"}


# ── Devices ───────────────────────────────────────────────────────────────────

@router.get("/devices")
async def spotify_devices(request: Request):
    user_id = _get_user_id(request)
    client = SpotifyClient(user_id)
    devices = await client.get_available_devices()
    return {"devices": [
        {"id": d.id, "name": d.name, "type": d.type, "is_active": d.is_active, "volume": d.volume_percent}
        for d in devices
    ]}


# ── Playback ──────────────────────────────────────────────────────────────────

@router.post("/play")
async def spotify_play(request: Request, body: PlayRequest):
    user_id = _get_user_id(request)
    client = SpotifyClient(user_id)
    try:
        await client.play(
            query=body.query,
            uri=body.uri,
            device_name=body.device_name,
            volume=body.volume,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "playing"}


@router.put("/pause")
async def spotify_pause(request: Request):
    user_id = _get_user_id(request)
    await SpotifyClient(user_id).pause()
    return {"status": "paused"}


@router.put("/resume")
async def spotify_resume(request: Request):
    user_id = _get_user_id(request)
    await SpotifyClient(user_id).resume()
    return {"status": "resumed"}


@router.put("/volume")
async def spotify_volume(request: Request, body: VolumeRequest):
    user_id = _get_user_id(request)
    await SpotifyClient(user_id).set_volume(body.percent)
    return {"status": "ok", "volume": body.percent}


@router.get("/now-playing")
async def spotify_now_playing(request: Request):
    user_id = _get_user_id(request)
    data = await SpotifyClient(user_id).get_currently_playing()
    if not data or not data.get("item"):
        return {"playing": False}
    item = data["item"]
    return {
        "playing": data.get("is_playing", False),
        "track": item.get("name"),
        "artist": ", ".join(a["name"] for a in item.get("artists", [])),
        "album": item.get("album", {}).get("name"),
        "progress_ms": data.get("progress_ms"),
        "duration_ms": item.get("duration_ms"),
    }
