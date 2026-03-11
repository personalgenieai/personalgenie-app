"""
routers/ingestion.py — Real-time ingestion progress via WebSocket.

The iOS app connects here during onboarding after Google/iMessage connect.
The server broadcasts friendly, human-voiced progress events as ingestion runs.

Flow:
  1. iOS calls POST /ingestion/session → gets session_id
  2. iOS opens WebSocket at GET /ws/ingestion/{session_id}
  3. iOS triggers ingestion (Google, iMessage, etc.)
  4. Ingestion services call POST /ingestion/progress/{session_id} to broadcast updates
  5. iOS receives events in Genie's voice — never technical

WhatsApp milestones fire at 0%, 20%, 80%, and 100%.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from pydantic import BaseModel

from config import get_settings
import database as db

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(tags=["ingestion"])

# ── In-memory session store ────────────────────────────────────────────────────
# Maps session_id → list of connected WebSocket clients.
# Intentionally in-memory: sessions are ephemeral (one onboarding, then gone).
_sessions: dict[str, list[WebSocket]] = {}

# Snapshot of the most-recent progress event per session (for GET /ingestion/status)
_snapshots: dict[str, dict] = {}

# WhatsApp milestone thresholds (progress %)
_WHATSAPP_MILESTONES: dict[int, str] = {
    0:   "I'm starting to read through your history. Give me a few minutes.",
    20:  "Still reading. Already I can see some familiar names.",
    80:  "Almost done building your picture.",
    100: "I'm ready.",   # 100% appends the first insight dynamically
}
# Track which milestones have already been sent per session to avoid repeats
_sent_milestones: dict[str, set[int]] = {}


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProgressEvent(BaseModel):
    source: str       # "google" | "imessage" | "calendar" | "maps"
    stage: str        # "starting" | "reading" | "analyzing" | "complete" | "error"
    progress: int     # 0-100
    message: str      # Genie's voice — never technical
    insight: str | None = None
    people_found: int = 0


class ProgressPushRequest(BaseModel):
    source: str
    stage: str
    progress: int
    message: str
    insight: str | None = None
    people_found: int = 0
    # Optional: user_id to look up phone for WhatsApp milestones
    user_id: str | None = None
    # Optional: top person insight for 100% WhatsApp message
    top_insight: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _milestone_bucket(progress: int) -> int | None:
    """
    Return the highest milestone threshold that this progress value crosses,
    or None if it doesn't cross any new milestone.
    Milestones: 0, 20, 80, 100.
    """
    for threshold in sorted(_WHATSAPP_MILESTONES.keys(), reverse=True):
        if progress >= threshold:
            return threshold
    return None


async def _send_whatsapp_milestone(
    session_id: str,
    progress: int,
    user_id: str | None,
    top_insight: str | None,
) -> None:
    """
    Send a WhatsApp message for a milestone if it hasn't been sent yet.
    Runs in fire-and-forget fashion — never blocks ingestion.
    """
    if not user_id:
        return

    bucket = _milestone_bucket(progress)
    if bucket is None:
        return

    already_sent = _sent_milestones.setdefault(session_id, set())
    if bucket in already_sent:
        return

    already_sent.add(bucket)
    message = _WHATSAPP_MILESTONES[bucket]

    # At 100%, append the first real insight if we have one
    if bucket == 100 and top_insight:
        message = f"{message} {top_insight}"

    try:
        user = db.get_user_by_id(user_id)
        if not user:
            return
        phone = user.get("phone", "")
        if not phone:
            return

        from services.whatsapp import send_message
        send_message(phone, message, user_id=user_id)
        logger.info(f"WhatsApp milestone {bucket}% sent to user {user_id}")
    except Exception as exc:
        logger.warning(f"WhatsApp milestone send failed (session={session_id}): {exc}")


# ── REST: create session ───────────────────────────────────────────────────────

@router.post("/ingestion/session")
async def create_session() -> dict:
    """
    Create a new ingestion session.
    iOS calls this first, gets session_id, then opens the WebSocket.
    """
    session_id = str(uuid.uuid4())
    _sessions[session_id] = []
    _snapshots[session_id] = {}
    _sent_milestones[session_id] = set()
    logger.info(f"Ingestion session created: {session_id}")
    return {"session_id": session_id}


class LinkUserRequest(BaseModel):
    user_id: str
    session_id: str


@router.post("/ingestion/link-user")
async def link_user_session(body: LinkUserRequest) -> dict:
    """
    iOS calls this after creating a session to associate it with the authenticated user.
    This allows ingestion services (google_ingestion, intelligence) to broadcast
    live learnings to the correct WebSocket connection by looking up the user's session.
    """
    from services.ingestion_bus import register as bus_register
    bus_register(body.user_id, body.session_id)
    # Ensure the session exists in the local registry too
    if body.session_id not in _sessions:
        _sessions[body.session_id] = []
        _snapshots[body.session_id] = {}
        _sent_milestones[body.session_id] = set()
    logger.info(f"Linked user {body.user_id} → session {body.session_id[:8]}…")
    return {"status": "linked", "user_id": body.user_id, "session_id": body.session_id}


# ── REST: push progress (called by ingestion services) ────────────────────────

@router.post("/ingestion/progress/{session_id}")
async def push_progress(session_id: str, body: ProgressPushRequest) -> dict:
    """
    Ingestion services call this to broadcast progress to all iOS clients
    currently watching this session via WebSocket.
    Also sends WhatsApp milestone messages at 0/20/80/100%.
    """
    if session_id not in _sessions:
        # Session may have been cleaned up; create it lazily
        _sessions[session_id] = []
        _snapshots[session_id] = {}
        _sent_milestones[session_id] = set()

    event: dict[str, Any] = {
        "source": body.source,
        "stage": body.stage,
        "progress": body.progress,
        "message": body.message,
        "insight": body.insight,
        "people_found": body.people_found,
    }

    # Persist latest snapshot for GET /ingestion/status
    _snapshots[session_id] = event

    # Broadcast to all connected WebSocket clients
    dead: list[WebSocket] = []
    for ws in list(_sessions.get(session_id, [])):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)

    # Clean up disconnected sockets
    for ws in dead:
        _sessions[session_id].remove(ws)

    # Fire WhatsApp milestone (non-blocking)
    asyncio.create_task(
        _send_whatsapp_milestone(
            session_id, body.progress, body.user_id, body.top_insight
        )
    )

    return {"broadcast_to": len(_sessions.get(session_id, [])), "session_id": session_id}


# ── REST: status snapshot ─────────────────────────────────────────────────────

@router.get("/ingestion/status/{session_id}")
async def get_status(session_id: str) -> dict:
    """
    Return the most recent progress snapshot for a session.
    Useful if the iOS app reconnects mid-ingestion and wants the current state.
    """
    if session_id not in _snapshots or not _snapshots[session_id]:
        raise HTTPException(status_code=404, detail="Session not found or no progress yet")
    return _snapshots[session_id]


# ── WebSocket: live progress stream ───────────────────────────────────────────

@router.websocket("/ws/ingestion/{session_id}")
async def ingestion_websocket(websocket: WebSocket, session_id: str) -> None:
    """
    iOS opens this WebSocket after receiving session_id from POST /ingestion/session.
    Receives ProgressEvent JSON objects as ingestion services push updates.

    If the session doesn't exist yet, it's created lazily here — the WebSocket
    connection may arrive before or after the first progress push.
    """
    await websocket.accept()

    # Register this connection
    if session_id not in _sessions:
        _sessions[session_id] = []
        _snapshots[session_id] = {}
        _sent_milestones[session_id] = set()

    _sessions[session_id].append(websocket)
    logger.info(f"WebSocket connected for session {session_id} — {len(_sessions[session_id])} client(s)")

    # If there's already a snapshot (client reconnected), send it immediately
    if _snapshots.get(session_id):
        try:
            await websocket.send_json(_snapshots[session_id])
        except Exception:
            pass

    try:
        # Keep the connection alive — we only send, but we need to handle disconnects
        while True:
            # Wait for any message (ping/pong or explicit close from iOS)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning(f"WebSocket error for session {session_id}: {exc}")
    finally:
        # Unregister on disconnect
        if session_id in _sessions and websocket in _sessions[session_id]:
            _sessions[session_id].remove(websocket)
        logger.info(f"WebSocket disconnected from session {session_id}")


class TriggerRequest(BaseModel):
    user_id: str

@router.post("/ingestion/trigger")
async def trigger_ingestion(body: TriggerRequest, background_tasks: BackgroundTasks):
    """Manually re-trigger Google ingestion + people graph rebuild for a user."""
    user = db.get_user_by_id(body.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    access_token = user.get("google_access_token")
    refresh_token = user.get("google_refresh_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No Google tokens found — user must re-authorize")

    async def _run():
        from services.google_ingestion import run_full_ingestion
        from services.intelligence import build_people_graph
        ingestion_data = await run_full_ingestion(body.user_id, access_token, refresh_token)
        build_people_graph(body.user_id, ingestion_data)
        logger.info(f"Manual ingestion complete for user {body.user_id}")

    background_tasks.add_task(_run)
    return {"status": "ingestion started", "user_id": body.user_id}
