"""
services/maps_processor.py — Google Maps Timeline → life signals pipeline.

Google Takeout location history reveals patterns:
  - Favourite restaurants / cafes → food & social interests
  - Gym / yoga / climbing visits → physical capability signals
  - Bookstore / library visits → intellectual signals
  - Airports / hotels in other cities → travel interest
  - Concert venues / theatres / museums → cultural interests

Pipeline per place visit:
  1. WorkFilter.classify(content_type="maps", ...)
  2. If personal → extract interest signals and save to place_visits
  3. Aggregate repeat visits: gym 12×  → strong physical signal
  4. Broadcast progress via session_id if provided

Expected Google Takeout format (simplified):
  [
    {
      "placeVisit": {
        "location": {
          "name": "Equinox SF",
          "address": "747 Market St, SF",
          "latitudeE7": 377741234,
          "longitudeE7": -1223938756
        },
        "duration": {
          "startTimestamp": "2024-03-01T14:00:00Z",
          "endTimestamp":   "2024-03-01T15:30:00Z"
        }
      }
    },
    ...
  ]

We also accept a flat format for testing / iOS upload:
  [
    {
      "place_name": "Equinox SF",
      "address": "747 Market St, SF",
      "visit_time": "2024-03-01T14:00:00Z",
      "duration_minutes": 90,
      "lat": 37.7741,
      "lng": -122.3939
    }
  ]
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from config import get_settings
from core.ingestion.work_filter import WorkFilter, Label
import database as db

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Place-type signal map ─────────────────────────────────────────────────────
# Maps keyword → (interest_category, capability_area | None, capability_delta)
_PLACE_SIGNALS: list[tuple[re.Pattern, str, str | None, float]] = [
    (re.compile(r"\b(restaurant|bistro|brasserie|eatery|sushi|taqueria|pizzeria|steakhouse|ramen|diner)\b", re.I),
     "food", None, 0.0),
    (re.compile(r"\b(cafe|coffee|espresso|brew|roaster)\b", re.I),
     "food", None, 0.0),
    (re.compile(r"\b(bar|pub|tavern|lounge|cocktail|brewery|winery|taproom)\b", re.I),
     "social", None, 0.0),
    (re.compile(r"\b(gym|fitness|equinox|crossfit|cycling|spin|f45|orange theory|barre|pilates|yoga|climbing|bouldering|swimming|pool)\b", re.I),
     "fitness", "physical", 0.2),
    (re.compile(r"\b(bookstore|library|books|literary)\b", re.I),
     "intellectual", None, 0.0),
    (re.compile(r"\b(airport|terminal|departures|arrivals)\b", re.I),
     "travel", None, 0.0),
    (re.compile(r"\b(hotel|hostel|airbnb|motel|inn|resort)\b", re.I),
     "travel", None, 0.0),
    (re.compile(r"\b(concert|theater|theatre|cinema|movie|museum|gallery|opera|ballet|comedy|venue)\b", re.I),
     "culture", None, 0.0),
    (re.compile(r"\b(park|trail|hike|nature|beach|forest)\b", re.I),
     "outdoors", "physical", 0.1),
]

# ── Progress broadcaster ──────────────────────────────────────────────────────

async def _broadcast(
    session_id: str | None,
    stage: str,
    progress: int,
    message: str,
    insight: str | None = None,
    user_id: str | None = None,
) -> None:
    if not session_id:
        return
    try:
        payload: dict[str, Any] = {
            "source": "maps",
            "stage": stage,
            "progress": progress,
            "message": message,
            "insight": insight,
            "people_found": 0,
            "user_id": user_id,
        }
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{settings.backend_url}/ingestion/progress/{session_id}",
                json=payload,
                timeout=5.0,
            )
    except Exception as exc:
        logger.debug(f"Maps progress broadcast failed (non-fatal): {exc}")


# ── Normalise Google Takeout entry ────────────────────────────────────────────

def _normalise(entry: dict) -> dict | None:
    """
    Accept either the nested Google Takeout format or the flat test format.
    Returns a normalised dict or None if unrecognisable.
    """
    # Google Takeout format
    if "placeVisit" in entry:
        pv = entry["placeVisit"]
        loc = pv.get("location", {})
        dur = pv.get("duration", {})

        start_ts = dur.get("startTimestamp", "")
        end_ts = dur.get("endTimestamp", "")
        duration_minutes = 0
        if start_ts and end_ts:
            try:
                t0 = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
                duration_minutes = max(0, int((t1 - t0).total_seconds() / 60))
            except Exception:
                pass

        lat = loc.get("latitudeE7", 0) / 1e7 if loc.get("latitudeE7") else None
        lng = loc.get("longitudeE7", 0) / 1e7 if loc.get("longitudeE7") else None

        return {
            "place_name": loc.get("name", ""),
            "address": loc.get("address", ""),
            "visit_time": start_ts,
            "duration_minutes": duration_minutes,
            "lat": lat,
            "lng": lng,
        }

    # Flat format (test / iOS upload)
    if "place_name" in entry:
        return entry

    return None


# ── MapsProcessor ─────────────────────────────────────────────────────────────

class MapsProcessor:
    """
    Processes Google Maps timeline data for one user.
    """

    def __init__(self) -> None:
        self._work_filter = WorkFilter()

    # ── Public API ────────────────────────────────────────────────────────────

    async def process_timeline(
        self,
        user_id: str,
        timeline_data: list[dict],
        session_id: str | None = None,
    ) -> dict:
        """
        Process a list of Google Takeout place visit entries.

        Returns:
          {
            "places_analyzed": int,
            "work_filtered": int,
            "interests_extracted": int,
            "places_saved": int,
          }
        """
        stats = {
            "places_analyzed": 0,
            "work_filtered": 0,
            "interests_extracted": 0,
            "places_saved": 0,
        }

        total = len(timeline_data)
        if total == 0:
            return stats

        await _broadcast(
            session_id, "starting", 0,
            "Reading your Maps history — looking for the places that define you.",
            user_id=user_id,
        )

        # Running tally: place_name → visit_count (for aggregate signals)
        visit_counts: dict[str, int] = {}

        for idx, raw_entry in enumerate(timeline_data):
            entry = _normalise(raw_entry)
            if entry is None:
                continue

            place_name = entry.get("place_name", "")
            if not place_name:
                continue

            # Progress broadcast roughly every 20%
            pct = 5 + int((idx / total) * 85)
            if idx % max(1, total // 5) == 0:
                await _broadcast(
                    session_id, "reading", pct,
                    f"Reading through the places you've been",
                    user_id=user_id,
                )

            # ── WorkFilter ─────────────────────────────────────────────────
            fr = await self._work_filter.classify(
                content_type="maps",
                content={
                    "place_name": place_name,
                    "address": entry.get("address", ""),
                    "visit_time": entry.get("visit_time", ""),
                    "duration_minutes": entry.get("duration_minutes", 0),
                },
                user_id=user_id,
            )

            if not fr.passes:
                stats["work_filtered"] += 1
                continue

            stats["places_analyzed"] += 1
            visit_counts[place_name] = visit_counts.get(place_name, 0) + 1

            # ── Save to place_visits (upsert by (user_id, place_name)) ─────
            try:
                self._upsert_place_visit(user_id, entry, visit_counts[place_name])
                stats["places_saved"] += 1
            except Exception as exc:
                logger.warning(f"Failed to save place visit '{place_name}': {exc}")

            # ── Extract interest signals ───────────────────────────────────
            signals_added = await self._extract_signals(user_id, entry, visit_counts[place_name])
            stats["interests_extracted"] += signals_added

        await _broadcast(
            session_id, "analyzing", 92,
            "Connecting the dots between your favourite places",
            user_id=user_id,
        )

        await _broadcast(
            session_id, "complete", 100,
            "Your world is taking shape",
            insight=f"Genie explored {stats['places_analyzed']} places from your history",
            user_id=user_id,
        )

        return stats

    # ── Private helpers ───────────────────────────────────────────────────────

    def _upsert_place_visit(self, user_id: str, entry: dict, visit_count: int) -> None:
        """
        Upsert a place_visits record.
        On conflict (user_id, place_name), update visit_count and last_visited.
        """
        db.get_db().table("place_visits").upsert(
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "place_name": entry.get("place_name", ""),
                "place_type": self._infer_place_type(entry.get("place_name", "")),
                "visit_count": visit_count,
                "last_visited": entry.get("visit_time") or None,
                "lat": entry.get("lat"),
                "lng": entry.get("lng"),
            },
            on_conflict="user_id,place_name",
        ).execute()

    def _infer_place_type(self, place_name: str) -> str:
        """Return a simple category for a place based on its name."""
        for pattern, category, _, _ in _PLACE_SIGNALS:
            if pattern.search(place_name):
                return category
        return "other"

    async def _extract_signals(
        self,
        user_id: str,
        entry: dict,
        visit_count: int,
    ) -> int:
        """
        Extract interest / capability signals for one place visit.
        Returns count of signals written.
        """
        place_name = entry.get("place_name", "")
        address = entry.get("address", "")
        combined = f"{place_name} {address}"
        signals_written = 0

        for pattern, interest_category, capability_area, base_delta in _PLACE_SIGNALS:
            if not pattern.search(combined):
                continue

            # ── Interest signal ────────────────────────────────────────────
            try:
                db.get_db().table("interest_signals").insert({
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "category": interest_category,
                    "source": "maps",
                    "note": f"Visited {place_name} (×{visit_count})",
                }).execute()
                signals_written += 1
            except Exception as exc:
                logger.debug(f"interest_signals insert skipped: {exc}")

            # ── Capability signal (if applicable) ─────────────────────────
            if capability_area and base_delta > 0:
                # Stronger signal for repeat visits
                delta = base_delta + min(0.1 * (visit_count - 1), 0.3)
                try:
                    db.get_db().table("capability_signals").insert({
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "capability_area": capability_area,
                        "delta": round(delta, 3),
                        "source": f"maps: {place_name[:80]} (visit #{visit_count})",
                    }).execute()
                    signals_written += 1
                except Exception as exc:
                    logger.debug(f"capability_signals insert skipped: {exc}")

            break  # one signal per place visit is enough

        return signals_written


# ── FastAPI router ────────────────────────────────────────────────────────────

try:
    from fastapi import APIRouter as _APIRouter, HTTPException as _HTTPException
    from pydantic import BaseModel as _BaseModel
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    _APIRouter = None  # type: ignore[assignment,misc]
    _HTTPException = None  # type: ignore[assignment,misc]
    from pydantic import BaseModel as _BaseModel

maps_router = _APIRouter(tags=["maps"]) if _FASTAPI_AVAILABLE else None  # type: ignore[assignment]

_processor = MapsProcessor()


class MapsTimelineRequest(_BaseModel):
    user_id: str
    timeline_data: list[dict]
    session_id: str | None = None


if _FASTAPI_AVAILABLE:
    @maps_router.post("/maps/timeline")
    async def maps_timeline(body: MapsTimelineRequest) -> dict:
        """
        iOS sends Google Takeout location history here.
        Accepts both the nested placeVisit format and the flat format.
        """
        if not body.user_id:
            raise _HTTPException(status_code=400, detail="user_id is required")

        result = await _processor.process_timeline(
            user_id=body.user_id,
            timeline_data=body.timeline_data,
            session_id=body.session_id,
        )

        return {
            "ok": True,
            **result,
            "message": (
                f"Genie explored {result['places_analyzed']} places and found "
                f"{result['interests_extracted']} interest signals."
            ),
        }
