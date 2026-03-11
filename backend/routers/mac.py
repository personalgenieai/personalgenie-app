"""
routers/mac.py — Mac Companion registration and discovery.

The Mac companion server calls POST /mac/register on startup.
The iOS app calls GET /mac/status to discover the Mac's local URL.
"""
import time
import logging
import requests
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mac", tags=["mac"])

# In-memory registration — survives single-worker restarts fine (companion re-registers on start)
_mac_registry: dict = {}   # { "url": str, "registered_at": float }
STALE_AFTER = 120          # seconds — if Mac hasn't re-registered in 2 min, treat as gone


class RegisterRequest(BaseModel):
    url: str   # e.g. "http://192.168.1.152:5001"


@router.post("/register")
def register_mac(body: RegisterRequest):
    """Mac companion calls this on startup to advertise its local URL."""
    _mac_registry["url"] = body.url.rstrip("/")
    _mac_registry["registered_at"] = time.time()
    logger.info(f"Mac companion registered at {body.url}")
    return {"status": "registered", "url": body.url}


@router.get("/status")
def mac_status():
    """
    iOS app polls this to find the Mac companion's local URL.
    Returns { connected: bool, url: str | null }.
    Health check is done by the iOS app directly (backend can't reach local IPs).
    """
    url = _mac_registry.get("url")
    registered_at = _mac_registry.get("registered_at", 0)

    if not url or (time.time() - registered_at) > STALE_AFTER:
        return {"connected": False, "url": None}

    return {"connected": True, "url": url}
