"""
routers/bluetooth.py — Bluetooth speaker management endpoints.

POST   /bluetooth/speakers          — register a speaker
GET    /bluetooth/speakers          — list user's speakers
PUT    /bluetooth/speakers/{id}     — rename
DELETE /bluetooth/speakers/{id}     — remove
POST   /bluetooth/route             — route audio to a speaker
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from services.bluetooth_service import BluetoothService
from routers.auth import verify_app_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bluetooth", tags=["bluetooth"])
_service = BluetoothService()


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_user_id(request: Request) -> str:
    token = request.headers.get("X-App-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-App-Token")
    payload = verify_app_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]


# ── Pydantic models ───────────────────────────────────────────────────────────

class RegisterSpeakerRequest(BaseModel):
    device_name: str       # CoreBluetooth name, e.g. "JBL Charge 5"
    bt_address: str        # Bluetooth MAC / UUID from CoreBluetooth
    user_given_name: str   # user's label: "Living Room", "Kitchen"


class RenameSpeakerRequest(BaseModel):
    name: str


class RouteAudioRequest(BaseModel):
    content_type: str      # "music" | "tts" | "moment"
    content: str           # text to speak or music search query
    speaker_name: Optional[str] = None  # None = any speaker


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/speakers")
async def register_speaker(request: Request, body: RegisterSpeakerRequest):
    """Register a Bluetooth speaker detected by the iOS app."""
    user_id = _get_user_id(request)
    try:
        speaker = await _service.register_speaker(
            user_id=user_id,
            device_name=body.device_name,
            bt_address=body.bt_address,
            user_given_name=body.user_given_name,
        )
    except Exception as exc:
        logger.error("register_speaker failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not register speaker")
    return speaker


@router.get("/speakers")
async def list_speakers(request: Request):
    """List all registered Bluetooth speakers for the authenticated user."""
    user_id = _get_user_id(request)
    speakers = await _service.get_speakers(user_id)
    return {"speakers": speakers}


@router.put("/speakers/{speaker_id}")
async def rename_speaker(request: Request, speaker_id: str, body: RenameSpeakerRequest):
    """Rename a registered speaker."""
    user_id = _get_user_id(request)
    try:
        speaker = await _service.update_speaker_name(user_id, speaker_id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("rename_speaker failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not rename speaker")
    return speaker


@router.delete("/speakers/{speaker_id}")
async def remove_speaker(request: Request, speaker_id: str):
    """Remove a registered speaker."""
    user_id = _get_user_id(request)
    try:
        await _service.remove_speaker(user_id, speaker_id)
    except Exception as exc:
        logger.error("remove_speaker failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not remove speaker")
    return {"status": "removed"}


@router.post("/route")
async def route_audio(request: Request, body: RouteAudioRequest):
    """
    Route audio content to a Bluetooth speaker.

    Returns routing decision: method ("spotify_connect" or "tts") and,
    for TTS, the text the iOS app should speak via AVSpeechSynthesizer.
    """
    if body.content_type not in {"music", "tts", "moment"}:
        raise HTTPException(
            status_code=400,
            detail="content_type must be 'music', 'tts', or 'moment'"
        )
    user_id = _get_user_id(request)
    try:
        result = await _service.route_audio(
            user_id=user_id,
            content_type=body.content_type,
            content=body.content,
            speaker_name=body.speaker_name,
        )
    except Exception as exc:
        logger.error("route_audio failed: %s", exc)
        raise HTTPException(status_code=500, detail="Audio routing failed")
    return result
