"""
SpotifyClient — Spotify Web API wrapper.

Handles:
  - OAuth 2.0 PKCE token storage and refresh
  - Playback control (play, pause, resume, skip, volume)
  - Track/playlist search and queue
  - Available Spotify Connect device enumeration
  - Recent listening history
  - Audio features (valence, energy, danceability) for mood inference

Token storage: Supabase music_connections table.
  Columns: user_id, provider ("spotify"), access_token, refresh_token,
           token_expires_at, scopes, device_preference
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

SPOTIFY_BASE = "https://api.spotify.com/v1"
SPOTIFY_ACCOUNTS = "https://accounts.spotify.com"

REQUIRED_SCOPES = (
    "user-read-recently-played "
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing "
    "user-library-read "
    "playlist-read-private "
    "user-top-read"
)


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class SpotifyDevice:
    id: str
    name: str
    type: str          # "Computer" | "Smartphone" | "Speaker" | "TV" | ...
    is_active: bool
    volume_percent: int


@dataclass
class AudioFeatures:
    track_id: str
    valence: float      # 0.0 (sad) → 1.0 (happy)
    energy: float       # 0.0 (calm) → 1.0 (intense)
    danceability: float
    tempo: float        # BPM
    acousticness: float
    instrumentalness: float


@dataclass
class RecentTrack:
    track_id: str
    name: str
    artist: str
    album: str
    played_at: str      # ISO-8601
    duration_ms: int


# ── SpotifyClient ─────────────────────────────────────────────────────────────


class SpotifyClient:
    """
    Per-user Spotify client. Instantiate with a user_id; token is loaded
    from the database on first API call and refreshed automatically.

    Usage:
        client = SpotifyClient(user_id)
        devices = await client.get_available_devices()
        await client.play(query="Miles Davis Kind of Blue", device_name="Living Room")
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0.0
        self._settings = get_settings()

    # ── Token management ──────────────────────────────────────────────────────

    async def _ensure_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        # Load from DB if not in memory
        if not self._refresh_token:
            await self._load_tokens_from_db()

        if not self._refresh_token:
            raise RuntimeError(f"No Spotify connection for user {self.user_id}")

        await self.refresh_token()
        return self._access_token  # type: ignore[return-value]

    async def _load_tokens_from_db(self) -> None:
        try:
            from db import get_db
            db = get_db()
            row = (
                db.table("music_connections")
                .select("access_token, refresh_token, token_expires_at")
                .eq("user_id", self.user_id)
                .eq("provider", "spotify")
                .single()
                .execute()
            )
            if row.data:
                self._access_token = row.data["access_token"]
                self._refresh_token = row.data["refresh_token"]
                self._token_expires_at = float(row.data.get("token_expires_at") or 0)
        except Exception as exc:
            logger.warning("Could not load Spotify tokens for %s: %s", self.user_id, exc)

    async def refresh_token(self) -> None:
        """Exchange refresh token for a new access token."""
        if not self._refresh_token:
            raise RuntimeError("No refresh token available")

        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{SPOTIFY_ACCOUNTS}/api/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": self._settings.spotify_client_id,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()

        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]

        await self._save_tokens_to_db()

    async def _save_tokens_to_db(self) -> None:
        try:
            from db import get_db
            db = get_db()
            db.table("music_connections").upsert({
                "user_id": self.user_id,
                "provider": "spotify",
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "token_expires_at": self._token_expires_at,
            }).execute()
        except Exception as exc:
            logger.warning("Could not save Spotify tokens for %s: %s", self.user_id, exc)

    # ── HTTP helper ───────────────────────────────────────────────────────────

    async def _api(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
    ) -> dict | None:
        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SPOTIFY_BASE}{path}"

        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.request(method, url, headers=headers, json=json, params=params)

        if resp.status_code == 204:
            return None   # Spotify returns 204 for successful playback commands
        if resp.status_code == 401:
            # Token expired mid-request — refresh and retry once
            await self.refresh_token()
            token = self._access_token
            headers["Authorization"] = f"Bearer {token}"
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.request(method, url, headers=headers, json=json, params=params)

        resp.raise_for_status()
        return resp.json() if resp.content else None

    # ── Devices ───────────────────────────────────────────────────────────────

    async def get_available_devices(self) -> list[SpotifyDevice]:
        """Return all Spotify Connect devices currently visible to this account."""
        data = await self._api("GET", "/me/player/devices")
        if not data:
            return []
        return [
            SpotifyDevice(
                id=d["id"],
                name=d["name"],
                type=d["type"],
                is_active=d["is_active"],
                volume_percent=d.get("volume_percent") or 0,
            )
            for d in data.get("devices", [])
        ]

    def _resolve_device_id(self, devices: list[SpotifyDevice], device_name: str | None) -> str | None:
        """Find device ID by fuzzy name match."""
        if not device_name:
            # Return active device, or first available
            active = next((d for d in devices if d.is_active), None)
            return (active or devices[0]).id if devices else None

        name_lower = device_name.lower()
        # Exact match first
        for d in devices:
            if d.name.lower() == name_lower:
                return d.id
        # Substring match
        for d in devices:
            if name_lower in d.name.lower() or d.name.lower() in name_lower:
                return d.id
        return None

    # ── Search ────────────────────────────────────────────────────────────────

    async def resolve_search(self, query: str) -> dict | None:
        """
        Search Spotify for a track, album, playlist, or artist.
        Returns the best match as a raw Spotify object dict, or None.

        The caller should pass the uri field to play().
        """
        data = await self._api("GET", "/search", params={
            "q": query,
            "type": "track,album,playlist,artist",
            "limit": 5,
        })
        if not data:
            return None

        # Priority: playlist > album > track > artist
        for category in ("playlists", "albums", "tracks", "artists"):
            items = data.get(category, {}).get("items", [])
            if items:
                return items[0]
        return None

    # ── Playback ──────────────────────────────────────────────────────────────

    async def play(
        self,
        query: str | None = None,
        uri: str | None = None,
        device_name: str | None = None,
        volume: int | None = None,
    ) -> None:
        """
        Start playback.

        Provide either:
          - query: free-text search ("Miles Davis Kind of Blue")
          - uri: Spotify URI directly ("spotify:album:xxxx")

        device_name: fuzzy-match against available Spotify Connect devices.
        volume: 0–100, set before playback starts.
        """
        devices = await self.get_available_devices()
        device_id = self._resolve_device_id(devices, device_name)

        if not uri and query:
            result = await self.resolve_search(query)
            if result:
                uri = result.get("uri")

        if not uri:
            raise ValueError(f"Could not resolve Spotify URI for query: {query!r}")

        # Transfer playback to device if needed
        if device_id:
            await self._api("PUT", "/me/player", json={"device_ids": [device_id], "play": False})

        # Build play body based on URI type
        body: dict = {}
        if ":track:" in uri:
            body["uris"] = [uri]
        else:
            body["context_uri"] = uri

        if device_id:
            body["device_id"] = device_id

        if volume is not None and device_id:
            await self._api("PUT", "/me/player/volume", params={
                "volume_percent": max(0, min(100, volume)),
                "device_id": device_id,
            })

        await self._api("PUT", "/me/player/play", json=body)

    async def pause(self) -> None:
        await self._api("PUT", "/me/player/pause")

    async def resume(self) -> None:
        await self._api("PUT", "/me/player/play", json={})

    async def skip_next(self) -> None:
        await self._api("POST", "/me/player/next")

    async def skip_previous(self) -> None:
        await self._api("POST", "/me/player/previous")

    async def set_volume(self, percent: int) -> None:
        await self._api("PUT", "/me/player/volume", params={"volume_percent": max(0, min(100, percent))})

    async def queue_track(self, uri: str) -> None:
        await self._api("POST", "/me/player/queue", params={"uri": uri})

    # ── Listening history ─────────────────────────────────────────────────────

    async def get_recent_listening(self, limit: int = 50) -> list[RecentTrack]:
        """Return the user's recently played tracks (max 50)."""
        data = await self._api("GET", "/me/player/recently-played", params={"limit": min(limit, 50)})
        if not data:
            return []

        tracks = []
        for item in data.get("items", []):
            t = item.get("track", {})
            tracks.append(RecentTrack(
                track_id=t.get("id", ""),
                name=t.get("name", ""),
                artist=", ".join(a["name"] for a in t.get("artists", [])),
                album=t.get("album", {}).get("name", ""),
                played_at=item.get("played_at", ""),
                duration_ms=t.get("duration_ms", 0),
            ))
        return tracks

    async def get_top_tracks(self, time_range: str = "medium_term", limit: int = 20) -> list[dict]:
        """time_range: short_term (4w), medium_term (6mo), long_term (all time)"""
        data = await self._api("GET", "/me/top/tracks", params={"time_range": time_range, "limit": limit})
        return data.get("items", []) if data else []

    async def get_top_artists(self, time_range: str = "medium_term", limit: int = 10) -> list[dict]:
        data = await self._api("GET", "/me/top/artists", params={"time_range": time_range, "limit": limit})
        return data.get("items", []) if data else []

    # ── Audio features ────────────────────────────────────────────────────────

    async def get_audio_features(self, track_ids: list[str]) -> list[AudioFeatures]:
        """
        Return audio features for up to 100 tracks.
        Used by MusicProvider to infer emotional/mood context.
        """
        if not track_ids:
            return []

        # Spotify allows max 100 IDs per request
        ids_str = ",".join(track_ids[:100])
        data = await self._api("GET", "/audio-features", params={"ids": ids_str})
        if not data:
            return []

        features = []
        for f in data.get("audio_features", []):
            if f:
                features.append(AudioFeatures(
                    track_id=f["id"],
                    valence=f["valence"],
                    energy=f["energy"],
                    danceability=f["danceability"],
                    tempo=f["tempo"],
                    acousticness=f["acousticness"],
                    instrumentalness=f["instrumentalness"],
                ))
        return features

    async def get_currently_playing(self) -> dict | None:
        """Return the currently playing track, or None."""
        return await self._api("GET", "/me/player/currently-playing")

    # ── Token exchange (called by OAuth router) ────────────────────────────────

    @classmethod
    async def exchange_code(cls, code: str, code_verifier: str, redirect_uri: str) -> dict:
        """
        Exchange PKCE authorization code for tokens.
        Returns the raw Spotify token response dict.
        """
        settings = get_settings()
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{SPOTIFY_ACCOUNTS}/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": settings.spotify_client_id,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json()
