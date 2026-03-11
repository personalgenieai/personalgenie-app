"""
MusicProvider — Unified music interface.

Sits above Spotify and Apple Music. The rest of the codebase never calls
SpotifyClient or AppleMusicClient directly — everything goes through here.

Preference order when both providers are connected:
  1. Spotify (better device targeting via Spotify Connect)
  2. Apple Music

Mood inference from audio features:
  Uses Spotify's valence (happiness) and energy dimensions to place the
  current listening into one of seven emotional states.

World Model integration:
  get_emotional_context() returns a dict ready for injection into the
  World Model's music section. Always included when either provider is
  connected (PRD: "Music context is always in the World Model").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from services.spotify_client import SpotifyClient, AudioFeatures

logger = logging.getLogger(__name__)


# ── Mood taxonomy ─────────────────────────────────────────────────────────────

class Mood(str, Enum):
    ENERGIZED = "energized"       # high valence + high energy
    HAPPY = "happy"               # high valence + medium energy
    PEACEFUL = "peaceful"         # high valence + low energy
    FOCUSED = "focused"           # medium valence + high energy
    NEUTRAL = "neutral"           # medium valence + medium energy
    MELANCHOLY = "melancholy"     # low valence + low energy
    INTENSE = "intense"           # low valence + high energy


def infer_mood_from_features(features: list[AudioFeatures]) -> Mood:
    """
    Infer mood from a list of AudioFeatures objects.
    Uses average valence and energy of the set.
    """
    if not features:
        return Mood.NEUTRAL

    avg_valence = sum(f.valence for f in features) / len(features)
    avg_energy = sum(f.energy for f in features) / len(features)

    # 3×3 grid: valence (low/med/high) × energy (low/med/high)
    if avg_valence >= 0.6:
        if avg_energy >= 0.6:
            return Mood.ENERGIZED
        elif avg_energy >= 0.35:
            return Mood.HAPPY
        else:
            return Mood.PEACEFUL
    elif avg_valence >= 0.35:
        if avg_energy >= 0.6:
            return Mood.FOCUSED
        else:
            return Mood.NEUTRAL
    else:
        if avg_energy >= 0.5:
            return Mood.INTENSE
        else:
            return Mood.MELANCHOLY


# ── EmotionalContext ──────────────────────────────────────────────────────────

@dataclass
class EmotionalContext:
    """Music-derived emotional context for the World Model."""
    provider: str                  # "spotify" | "apple_music" | "both"
    current_track: str | None      # "Artist — Track Name"
    recent_artists: list[str]      # top 5 recent artists
    mood: Mood
    avg_valence: float             # 0–1
    avg_energy: float              # 0–1
    listening_active: bool         # is something playing right now?
    summary: str                   # one-sentence human-readable summary for Claude

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "current_track": self.current_track,
            "recent_artists": self.recent_artists,
            "mood": self.mood.value,
            "avg_valence": round(self.avg_valence, 2),
            "avg_energy": round(self.avg_energy, 2),
            "listening_active": self.listening_active,
            "summary": self.summary,
        }


# ── MusicProvider ─────────────────────────────────────────────────────────────

class MusicProvider:
    """
    Unified music capability for a single user.

    Instantiate per-request with a user_id. Discovers which providers are
    connected and routes accordingly.

    Usage:
        mp = MusicProvider(user_id)
        await mp.play("something calm for focus")
        ctx = await mp.get_emotional_context()
        world_model["music"] = ctx.to_dict()
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._spotify: SpotifyClient | None = None
        self._has_spotify: bool | None = None   # None = not yet checked

    # ── Provider availability ─────────────────────────────────────────────────

    async def _check_spotify(self) -> bool:
        if self._has_spotify is not None:
            return self._has_spotify
        try:
            from db import get_db
            db = get_db()
            row = (
                db.table("music_connections")
                .select("user_id")
                .eq("user_id", self.user_id)
                .eq("provider", "spotify")
                .execute()
            )
            self._has_spotify = bool(row.data)
        except Exception:
            self._has_spotify = False
        return self._has_spotify

    def _get_spotify(self) -> SpotifyClient:
        if self._spotify is None:
            self._spotify = SpotifyClient(self.user_id)
        return self._spotify

    # ── Playback ──────────────────────────────────────────────────────────────

    async def play(
        self,
        query: str | None = None,
        uri: str | None = None,
        device_name: str | None = None,
        provider_preference: str = "spotify",
        volume: int | None = None,
    ) -> dict:
        """
        Play music via the best available provider.

        provider_preference: "spotify" | "apple_music" — used when both connected.
        Returns {"provider": "spotify"|"apple_music", "status": "playing"}.
        """
        has_spotify = await self._check_spotify()

        if has_spotify and provider_preference != "apple_music":
            await self._get_spotify().play(query=query, uri=uri, device_name=device_name, volume=volume)
            return {"provider": "spotify", "status": "playing"}

        # Apple Music fallback (Phase 2 — iOS-side MusicKit)
        raise NotImplementedError(
            "Apple Music playback requires iOS MusicKit integration (Phase 2). "
            "Connect Spotify to play music from Genie."
        )

    async def pause(self) -> None:
        if await self._check_spotify():
            await self._get_spotify().pause()

    async def resume(self) -> None:
        if await self._check_spotify():
            await self._get_spotify().resume()

    async def get_devices(self) -> list[dict]:
        devices = []
        if await self._check_spotify():
            spotify_devices = await self._get_spotify().get_available_devices()
            devices += [
                {"name": d.name, "type": d.type, "provider": "spotify",
                 "is_active": d.is_active, "id": d.id}
                for d in spotify_devices
            ]
        return devices

    # ── Emotional context ─────────────────────────────────────────────────────

    async def get_emotional_context(self) -> EmotionalContext | None:
        """
        Build the music emotional context for the World Model.
        Returns None only if no music provider is connected at all.
        """
        has_spotify = await self._check_spotify()

        if not has_spotify:
            return None

        return await self._build_spotify_context()

    async def _build_spotify_context(self) -> EmotionalContext:
        spotify = self._get_spotify()

        # Current track
        current_track: str | None = None
        listening_active = False
        try:
            now = await spotify.get_currently_playing()
            if now and now.get("item") and now.get("is_playing"):
                item = now["item"]
                artist = ", ".join(a["name"] for a in item.get("artists", []))
                current_track = f"{artist} — {item.get('name', '')}"
                listening_active = True
        except Exception:
            pass

        # Recent tracks + audio features for mood
        features: list[AudioFeatures] = []
        recent_artists: list[str] = []
        try:
            recent = await spotify.get_recent_listening(limit=20)
            track_ids = [t.track_id for t in recent if t.track_id]
            if track_ids:
                features = await spotify.get_audio_features(track_ids)

            # Top 5 unique recent artists
            seen: set[str] = set()
            for t in recent:
                for artist in t.artist.split(", "):
                    if artist and artist not in seen:
                        seen.add(artist)
                        recent_artists.append(artist)
                    if len(recent_artists) >= 5:
                        break
                if len(recent_artists) >= 5:
                    break
        except Exception as exc:
            logger.warning("Could not fetch recent Spotify history for %s: %s", self.user_id, exc)

        mood = infer_mood_from_features(features)
        avg_valence = sum(f.valence for f in features) / len(features) if features else 0.5
        avg_energy = sum(f.energy for f in features) / len(features) if features else 0.5

        summary = _build_summary(current_track, mood, recent_artists, listening_active)

        return EmotionalContext(
            provider="spotify",
            current_track=current_track,
            recent_artists=recent_artists,
            mood=mood,
            avg_valence=avg_valence,
            avg_energy=avg_energy,
            listening_active=listening_active,
            summary=summary,
        )


# ── Summary builder ───────────────────────────────────────────────────────────

def _build_summary(
    current_track: str | None,
    mood: Mood,
    recent_artists: list[str],
    listening_active: bool,
) -> str:
    """Build a one-sentence summary for Claude's World Model context string."""
    mood_phrases = {
        Mood.ENERGIZED: "in an energized, upbeat headspace",
        Mood.HAPPY:     "in a happy, positive mood",
        Mood.PEACEFUL:  "in a calm, peaceful state",
        Mood.FOCUSED:   "in a focused, driven state",
        Mood.NEUTRAL:   "in a balanced, neutral headspace",
        Mood.MELANCHOLY:"in a reflective, melancholy mood",
        Mood.INTENSE:   "in an intense, charged emotional state",
    }

    artists_str = ""
    if recent_artists:
        if len(recent_artists) == 1:
            artists_str = f" Recent listening: {recent_artists[0]}."
        else:
            artists_str = f" Recent listening: {', '.join(recent_artists[:3])}."

    if listening_active and current_track:
        return f"Currently listening to {current_track} — {mood_phrases[mood]}.{artists_str}"
    elif recent_artists:
        return f"Recent music suggests they are {mood_phrases[mood]}.{artists_str}"
    else:
        return f"Music connected but no recent listening data available."
