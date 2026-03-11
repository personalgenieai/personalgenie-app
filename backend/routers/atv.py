"""
routers/atv.py — Apple TV control endpoints.

GET  /atv/discover            — discover Apple TVs on network
POST /atv/command             — send a single remote command
POST /atv/macros              — create (record) a macro
GET  /atv/macros              — list macros for this user
POST /atv/macros/{name}/play  — execute a macro by name
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from services.atv_service import ATVService, VALID_COMMANDS
from routers.auth import verify_app_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/atv", tags=["atv"])


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

class CommandRequest(BaseModel):
    identifier: str     # ATV device identifier
    command: str        # must be in VALID_COMMANDS


class CreateMacroRequest(BaseModel):
    macro_name: str
    commands: list[str]
    device_identifier: Optional[str] = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/discover")
async def discover_atvs(request: Request):
    """
    Scan the local network for Apple TV devices.
    Returns list of {name, identifier, address, model}.
    Note: the backend must be on the same network as the Apple TVs.
    """
    user_id = _get_user_id(request)
    service = ATVService(user_id)
    devices = await service.discover_devices()
    return {"devices": devices}


@router.post("/command")
async def send_command(request: Request, body: CommandRequest):
    """Send a single remote-control command to an Apple TV."""
    user_id = _get_user_id(request)
    if body.command not in VALID_COMMANDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown command '{body.command}'. Valid: {sorted(VALID_COMMANDS)}"
        )
    service = ATVService(user_id)
    success = await service.send_command(body.identifier, body.command)
    if not success:
        raise HTTPException(status_code=502, detail="Command failed or device unreachable")
    return {"status": "sent", "command": body.command}


@router.post("/macros")
async def create_macro(request: Request, body: CreateMacroRequest):
    """Create or update a named macro (sequence of ATV commands)."""
    user_id = _get_user_id(request)
    if not body.macro_name.strip():
        raise HTTPException(status_code=400, detail="macro_name is required")
    if not body.commands:
        raise HTTPException(status_code=400, detail="commands list cannot be empty")

    invalid = [c for c in body.commands if c not in VALID_COMMANDS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown commands: {invalid}. Valid: {sorted(VALID_COMMANDS)}"
        )

    service = ATVService(user_id)
    try:
        macro = await service.record_macro(
            user_id=user_id,
            macro_name=body.macro_name,
            commands=body.commands,
            device_identifier=body.device_identifier or "",
        )
    except Exception as exc:
        logger.error("create_macro failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not save macro")
    return macro


@router.get("/macros")
async def list_macros(request: Request):
    """List all macros for the authenticated user."""
    user_id = _get_user_id(request)
    service = ATVService(user_id)
    macros = await service.get_macros(user_id)
    return {"macros": macros}


@router.post("/macros/{name}/play")
async def play_macro(request: Request, name: str):
    """Execute a named macro. Sends each command sequentially."""
    user_id = _get_user_id(request)
    service = ATVService(user_id)
    success = await service.play_macro(user_id, name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Macro '{name}' not found or failed")
    return {"status": "executed", "macro": name}
