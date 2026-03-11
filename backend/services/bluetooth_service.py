"""
services/bluetooth_service.py — Bluetooth speaker management (backend side).

The iOS app detects Bluetooth devices via CoreBluetooth and registers them here.
The backend stores speaker metadata and routing preferences, and decides HOW to
route audio (Spotify Connect vs. TTS instruction back to iOS).

Architecture note:
  - Music playback → try Spotify Connect (target device by name); fall back to
    returning a TTS announcement for the iOS app to speak.
  - TTS / Genie voice / moment reading → backend generates text, returns a
    structured response for iOS to speak via AVSpeechSynthesizer.
    The backend NEVER sends audio bytes — it sends text + routing instructions.

Storage: bluetooth_speakers table.
  Columns: id, user_id, device_name, bt_address, user_given_name,
           routing_preference, created_at.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class BluetoothService:
    """
    Manages registered Bluetooth speakers per user and routes audio requests.

    Usage:
        svc = BluetoothService()
        speaker = await svc.register_speaker(user_id, "JBL Charge 5", "AA:BB:CC:DD", "Kitchen")
        result = await svc.route_audio(user_id, "tts", "Your 3pm meeting starts in 10 minutes")
    """

    # ── Speaker registration ──────────────────────────────────────────────────

    async def register_speaker(
        self,
        user_id: str,
        device_name: str,       # e.g. "JBL Charge 5" (from CoreBluetooth)
        bt_address: str,        # Bluetooth MAC address or UUID
        user_given_name: str,   # user's label: "Living Room", "Kitchen", etc.
    ) -> dict:
        """
        Register a Bluetooth speaker for a user.
        If a speaker with the same bt_address already exists for this user, update it.
        Returns the saved speaker record.
        """
        try:
            import database as db_mod
            db = db_mod.get_db()

            # Check if already registered
            existing = (
                db.table("bluetooth_speakers")
                .select("id")
                .eq("user_id", user_id)
                .eq("bt_address", bt_address)
                .execute()
            )

            speaker_id = existing.data[0]["id"] if existing.data else str(uuid.uuid4())
            row = {
                "id": speaker_id,
                "user_id": user_id,
                "device_name": device_name,
                "bt_address": bt_address,
                "user_given_name": user_given_name,
                "routing_preference": "auto",  # "auto" | "tts_only" | "spotify_only"
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if not existing.data:
                row["created_at"] = datetime.now(timezone.utc).isoformat()
                result = db.table("bluetooth_speakers").insert(row).execute()
            else:
                result = (
                    db.table("bluetooth_speakers")
                    .update(row)
                    .eq("id", speaker_id)
                    .execute()
                )

            return result.data[0] if result.data else row

        except Exception as exc:
            logger.error("Could not register speaker for %s: %s", user_id, exc)
            raise

    async def get_speakers(self, user_id: str) -> list[dict]:
        """Return all registered speakers for a user."""
        try:
            import database as db_mod
            db = db_mod.get_db()
            result = (
                db.table("bluetooth_speakers")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=False)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.error("Could not fetch speakers for %s: %s", user_id, exc)
            return []

    async def update_speaker_name(
        self, user_id: str, speaker_id: str, name: str
    ) -> dict:
        """Rename a registered speaker."""
        try:
            import database as db_mod
            db = db_mod.get_db()
            result = (
                db.table("bluetooth_speakers")
                .update({"user_given_name": name})
                .eq("id", speaker_id)
                .eq("user_id", user_id)
                .execute()
            )
            if not result.data:
                raise ValueError(f"Speaker {speaker_id} not found for user {user_id}")
            return result.data[0]
        except Exception as exc:
            logger.error("Could not rename speaker %s: %s", speaker_id, exc)
            raise

    async def remove_speaker(self, user_id: str, speaker_id: str) -> None:
        """Remove a registered speaker."""
        try:
            import database as db_mod
            db = db_mod.get_db()
            db.table("bluetooth_speakers").delete().eq("id", speaker_id).eq("user_id", user_id).execute()
        except Exception as exc:
            logger.error("Could not remove speaker %s: %s", speaker_id, exc)
            raise

    # ── Audio routing ─────────────────────────────────────────────────────────

    async def route_audio(
        self,
        user_id: str,
        content_type: str,          # "music" | "tts" | "moment"
        content: str,               # text to speak or music query
        speaker_name: Optional[str] = None,  # None = any speaker
    ) -> dict:
        """
        Route audio to a Bluetooth speaker.

        Returns a routing decision dict:
          {
            "routed": bool,
            "method": "spotify_connect" | "tts",
            "speaker": str,          # user_given_name of target speaker
            "tts_text": str | None,  # text for iOS AVSpeechSynthesizer
            "spotify_query": str | None,
          }

        Music routing:
          1. Try Spotify Connect (target device by user_given_name).
          2. If no Spotify connection or no matching device, fall back to
             returning a TTS announcement.

        TTS / moment routing:
          Backend returns structured text; iOS speaks it via AVSpeechSynthesizer.
        """
        speakers = await self.get_speakers(user_id)

        # Resolve target speaker
        target_speaker = None
        if speaker_name:
            for s in speakers:
                if s.get("user_given_name", "").lower() == speaker_name.lower():
                    target_speaker = s
                    break
        elif speakers:
            target_speaker = speakers[0]  # default to first registered

        speaker_label = target_speaker["user_given_name"] if target_speaker else "Unknown"

        if content_type == "music":
            return await self._route_music(user_id, content, target_speaker, speaker_label)

        # TTS and moment content: always text-back to iOS
        tts_text = self._prepare_tts_text(content_type, content)
        return {
            "routed": bool(target_speaker),
            "method": "tts",
            "speaker": speaker_label,
            "tts_text": tts_text,
            "spotify_query": None,
        }

    async def _route_music(
        self,
        user_id: str,
        query: str,
        target_speaker: Optional[dict],
        speaker_label: str,
    ) -> dict:
        """Try Spotify Connect first; fall back to TTS announcement."""
        # Attempt Spotify Connect routing
        try:
            from services.spotify_client import SpotifyClient
            spotify = SpotifyClient(user_id)
            devices = await spotify.get_available_devices()

            spotify_device = None
            if target_speaker:
                name_lower = target_speaker.get("user_given_name", "").lower()
                for device in devices:
                    if name_lower in device.name.lower() or device.name.lower() in name_lower:
                        spotify_device = device
                        break
            elif devices:
                spotify_device = next((d for d in devices if d.is_active), devices[0])

            if spotify_device:
                await spotify.play(query=query, device_name=spotify_device.name)
                return {
                    "routed": True,
                    "method": "spotify_connect",
                    "speaker": speaker_label,
                    "tts_text": None,
                    "spotify_query": query,
                }
        except Exception as exc:
            logger.info("Spotify Connect routing failed (%s), falling back to TTS", exc)

        # Fallback: TTS announcement
        tts_text = f"Now playing: {query}"
        return {
            "routed": bool(target_speaker),
            "method": "tts",
            "speaker": speaker_label,
            "tts_text": tts_text,
            "spotify_query": None,
        }

    def _prepare_tts_text(self, content_type: str, content: str) -> str:
        """Clean up text for TTS delivery. Strips markdown, keeps it conversational."""
        # Remove markdown bold/italic
        import re
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", content)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        text = text.strip()

        if content_type == "moment":
            # Moment announcements get a brief prefix
            return f"Here's something for you. {text}"
        return text
