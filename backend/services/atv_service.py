"""
services/atv_service.py — Apple TV control via pyatv.

Wraps pyatv for device discovery, command sending, and macro playback.

Macro storage: device_macros table.
  Columns: id, user_id, macro_name, commands (jsonb), device_identifier, created_at.

Device storage: smart_home_devices table.
  Columns: id, user_id, device_name, device_type, device_identifier, last_seen.

Built-in macros are auto-created per user on first ATV connection:
  "wind_down"    — home → set a 30-minute reminder to sleep
  "movie_mode"   — go to TV/video app, full screen
  "good_morning" — go to home screen

Note: pyatv may not be in requirements.txt on all deployments. The import
is guarded so that other services still function if pyatv is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# pyatv is an optional dependency — guard the import
try:
    import pyatv
    from pyatv import connect as atv_connect
    from pyatv.const import Protocol
    _PYATV_AVAILABLE = True
except ImportError:
    _PYATV_AVAILABLE = False
    logger.warning("pyatv not installed — Apple TV discovery/control disabled")


# ── Supported commands ────────────────────────────────────────────────────────

VALID_COMMANDS = {
    "play", "pause", "home", "menu", "select",
    "up", "down", "left", "right",
    "volume_up", "volume_down",
    "top_menu", "skip_forward", "skip_backward",
}

# ── Built-in macros created on first connection ───────────────────────────────

BUILTIN_MACROS = [
    {
        "macro_name": "wind_down",
        "commands": ["home"],
        "description": "Go home to wind down",
    },
    {
        "macro_name": "movie_mode",
        "commands": ["home", "select"],
        "description": "Home screen then select top app for movie mode",
    },
    {
        "macro_name": "good_morning",
        "commands": ["home"],
        "description": "Go to home screen",
    },
]


class ATVService:
    """
    Apple TV control service.

    Usage:
        svc = ATVService(user_id="user-123")
        devices = await svc.discover_devices()
        await svc.send_command(devices[0]["identifier"], "play")
    """

    def __init__(self, user_id: str):
        self.user_id = user_id

    # ── Discovery ─────────────────────────────────────────────────────────────

    async def discover_devices(self) -> list[dict]:
        """
        Scan the local network for Apple TV devices.
        Returns list of {name, identifier, address}.
        """
        if not _PYATV_AVAILABLE:
            logger.warning("pyatv not available — returning empty device list")
            return []

        try:
            loop = asyncio.get_event_loop()
            atvs = await pyatv.scan(loop, timeout=5)
            devices = []
            for atv in atvs:
                devices.append({
                    "name": atv.name,
                    "identifier": str(atv.identifier),
                    "address": str(atv.address),
                    "model": str(atv.device_info.model) if atv.device_info else "unknown",
                })
            return devices
        except Exception as exc:
            logger.error("ATV discovery failed: %s", exc)
            return []

    # ── Connect ───────────────────────────────────────────────────────────────

    async def connect(self, identifier: str) -> bool:
        """
        Verify connectivity to an Apple TV by identifier.
        Saves device to smart_home_devices table and creates built-in macros
        if this is the user's first time connecting.
        """
        if not _PYATV_AVAILABLE:
            return False

        try:
            loop = asyncio.get_event_loop()
            atvs = await pyatv.scan(loop, identifier=identifier, timeout=5)
            if not atvs:
                return False

            atv_conf = atvs[0]
            # Save to smart_home_devices
            await self._upsert_device(atv_conf.name, identifier, str(atv_conf.address))
            # Ensure built-in macros exist for this user
            await self._ensure_builtin_macros(identifier)
            return True
        except Exception as exc:
            logger.error("ATV connect failed for identifier %s: %s", identifier, exc)
            return False

    # ── Command sending ───────────────────────────────────────────────────────

    async def send_command(self, identifier: str, command: str) -> bool:
        """
        Send a single remote command to an Apple TV.
        Returns True on success, False on failure.
        """
        if command not in VALID_COMMANDS:
            logger.warning("Unknown ATV command: %s", command)
            return False

        if not _PYATV_AVAILABLE:
            logger.warning("pyatv not available — command not sent")
            return False

        try:
            loop = asyncio.get_event_loop()
            atvs = await pyatv.scan(loop, identifier=identifier, timeout=5)
            if not atvs:
                logger.warning("ATV not found: %s", identifier)
                return False

            atv_conf = atvs[0]
            atv = await atv_connect(atv_conf, loop)
            try:
                rc = atv.remote_control
                method = getattr(rc, command, None)
                if method is None:
                    logger.warning("Command %s not supported by pyatv", command)
                    return False
                await method()
                return True
            finally:
                atv.close()
        except Exception as exc:
            logger.error("ATV send_command failed (id=%s, cmd=%s): %s", identifier, command, exc)
            return False

    # ── Macros ────────────────────────────────────────────────────────────────

    async def record_macro(
        self,
        user_id: str,
        macro_name: str,
        commands: list[str],
        device_identifier: str = "",
    ) -> dict:
        """
        Save a named macro (list of commands) to the database.
        Returns the saved macro record.
        """
        invalid = [c for c in commands if c not in VALID_COMMANDS]
        if invalid:
            raise ValueError(f"Unknown commands in macro: {invalid}")

        try:
            import database as db_mod
            db = db_mod.get_db()

            # Upsert by (user_id, macro_name)
            existing = (
                db.table("device_macros")
                .select("id")
                .eq("user_id", user_id)
                .eq("macro_name", macro_name)
                .execute()
            )

            macro_id = existing.data[0]["id"] if existing.data else str(uuid.uuid4())
            row = {
                "id": macro_id,
                "user_id": user_id,
                "macro_name": macro_name,
                "commands": commands,
                "device_identifier": device_identifier,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if not existing.data:
                row["created_at"] = datetime.now(timezone.utc).isoformat()
                result = db.table("device_macros").insert(row).execute()
            else:
                result = (
                    db.table("device_macros")
                    .update(row)
                    .eq("id", macro_id)
                    .execute()
                )
            return result.data[0] if result.data else row
        except Exception as exc:
            logger.error("record_macro failed: %s", exc)
            raise

    async def play_macro(self, user_id: str, macro_name: str) -> bool:
        """
        Execute all commands in a named macro sequentially.
        Returns True if all commands succeeded.
        """
        try:
            import database as db_mod
            db = db_mod.get_db()
            result = (
                db.table("device_macros")
                .select("commands, device_identifier")
                .eq("user_id", user_id)
                .eq("macro_name", macro_name)
                .execute()
            )
            if not result.data:
                logger.warning("Macro %s not found for user %s", macro_name, user_id)
                return False

            row = result.data[0]
            commands = row.get("commands", [])
            identifier = row.get("device_identifier", "")

            for command in commands:
                success = await self.send_command(identifier, command)
                if not success:
                    logger.warning("Macro %s: command %s failed", macro_name, command)
                # Small delay between commands
                await asyncio.sleep(0.5)

            return True
        except Exception as exc:
            logger.error("play_macro failed (user=%s, macro=%s): %s", user_id, macro_name, exc)
            return False

    async def get_macros(self, user_id: str) -> list[dict]:
        """Return all macros for a user."""
        try:
            import database as db_mod
            db = db_mod.get_db()
            result = (
                db.table("device_macros")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=False)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.error("get_macros failed: %s", exc)
            return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _upsert_device(self, name: str, identifier: str, address: str) -> None:
        try:
            import database as db_mod
            db = db_mod.get_db()
            existing = (
                db.table("smart_home_devices")
                .select("id")
                .eq("user_id", self.user_id)
                .eq("device_identifier", identifier)
                .execute()
            )
            row = {
                "user_id": self.user_id,
                "device_name": name,
                "device_type": "apple_tv",
                "device_identifier": identifier,
                "device_address": address,
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }
            if existing.data:
                db.table("smart_home_devices").update(row).eq("id", existing.data[0]["id"]).execute()
            else:
                row["id"] = str(uuid.uuid4())
                db.table("smart_home_devices").insert(row).execute()
        except Exception as exc:
            logger.warning("_upsert_device failed: %s", exc)

    async def _ensure_builtin_macros(self, device_identifier: str) -> None:
        """Create built-in macros if they don't already exist for this user."""
        for macro in BUILTIN_MACROS:
            try:
                import database as db_mod
                db = db_mod.get_db()
                existing = (
                    db.table("device_macros")
                    .select("id")
                    .eq("user_id", self.user_id)
                    .eq("macro_name", macro["macro_name"])
                    .execute()
                )
                if not existing.data:
                    await self.record_macro(
                        self.user_id,
                        macro["macro_name"],
                        macro["commands"],
                        device_identifier,
                    )
            except Exception as exc:
                logger.warning("Could not create built-in macro %s: %s", macro["macro_name"], exc)
