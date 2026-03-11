"""
services/ingestion_bus.py — Shared ingestion progress bus.

Holds the user_id → session_id mapping (ephemeral, in-memory).
Used by google_ingestion.py and intelligence.py to broadcast live
learnings to the iOS app during onboarding without importing from routers.
"""
import logging
import httpx
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# user_id → active onboarding session_id
# Ephemeral: only lives for the duration of onboarding. Cleared after 100%.
_user_sessions: dict[str, str] = {}


def register(user_id: str, session_id: str) -> None:
    """Called when iOS links its onboarding session to a user."""
    _user_sessions[user_id] = session_id
    logger.info(f"Ingestion bus: registered session {session_id[:8]}… for user {user_id}")


def get_session(user_id: str) -> str | None:
    return _user_sessions.get(user_id)


def clear(user_id: str) -> None:
    _user_sessions.pop(user_id, None)


def broadcast_sync(
    session_id: str,
    source: str,
    stage: str,
    progress: int,
    message: str,
    insight: str | None = None,
    people_found: int = 0,
    user_id: str | None = None,
) -> None:
    """
    Synchronous fire-and-forget broadcast.
    Safe to call from sync functions (e.g. build_people_graph).
    Never raises — failures are logged at DEBUG level only.
    """
    try:
        with httpx.Client(timeout=3.0) as client:
            client.post(
                f"{settings.backend_url}/ingestion/progress/{session_id}",
                json={
                    "source":       source,
                    "stage":        stage,
                    "progress":     progress,
                    "message":      message,
                    "insight":      insight,
                    "people_found": people_found,
                    "user_id":      user_id,
                },
            )
    except Exception as exc:
        logger.debug(f"Ingestion broadcast (sync) non-fatal: {exc}")


async def broadcast_async(
    session_id: str,
    source: str,
    stage: str,
    progress: int,
    message: str,
    insight: str | None = None,
    people_found: int = 0,
    user_id: str | None = None,
) -> None:
    """
    Async broadcast. Use from async ingestion functions.
    Never raises.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(
                f"{settings.backend_url}/ingestion/progress/{session_id}",
                json={
                    "source":       source,
                    "stage":        stage,
                    "progress":     progress,
                    "message":      message,
                    "insight":      insight,
                    "people_found": people_found,
                    "user_id":      user_id,
                },
            )
    except Exception as exc:
        logger.debug(f"Ingestion broadcast (async) non-fatal: {exc}")
