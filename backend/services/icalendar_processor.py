"""
services/icalendar_processor.py — iCalendar events → life signals pipeline.

The iOS app sends calendar events through POST /calendar/sync.
This processor:
  1. Runs WorkFilter on every event
  2. Saves personal events to the `calendar_events` table
  3. Extracts life signals: birthdays → life_events, travel → interests,
     health appointments → health signals, large social gatherings → social signals

All life signal extraction is fire-and-forget — it never blocks the sync response.
Work events are counted and discarded; their content never reaches the signal layer.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    _FASTAPI_AVAILABLE = True
except ImportError:
    # Tests may run without fastapi in the venv
    _FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    from pydantic import BaseModel

from config import get_settings
from core.ingestion.work_filter import WorkFilter, Label
import database as db

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Router (thin, attached to processor module for locality) ──────────────────
router = APIRouter(tags=["calendar"]) if _FASTAPI_AVAILABLE else None  # type: ignore[assignment]


# ── Regex patterns for life signal extraction ─────────────────────────────────

_BIRTHDAY_RE = re.compile(r"\b(birthday|bday)\b", re.I)
_ANNIVERSARY_RE = re.compile(r"\b(anniversary|anniversaire)\b", re.I)
_TRAVEL_RE = re.compile(r"\b(flight|travel|vacation|holiday|trip|airport|hotel)\b", re.I)
_HEALTH_RE = re.compile(r"\b(doctor|dentist|therapist|therapy|physio|chiro|optom|appointment|checkup|check.up)\b", re.I)
_GYM_RE = re.compile(r"\b(gym|yoga|run|hike|workout|crossfit|climbing|pilates|swim|cycle|cycling)\b", re.I)


# ── Schemas ───────────────────────────────────────────────────────────────────

class CalendarEvent(BaseModel):
    title: str
    description: str = ""
    start_time: str          # ISO-8601
    end_time: str = ""
    calendar_name: str = ""
    attendees: list[str] = []


class CalendarSyncRequest(BaseModel):
    user_id: str
    events: list[CalendarEvent]
    selected_calendars: list[str] | None = None


# ── ICalendarProcessor ────────────────────────────────────────────────────────

class ICalendarProcessor:
    """
    Processes a batch of calendar events for one user.
    """

    def __init__(self) -> None:
        self._work_filter = WorkFilter()

    # ── Public API ────────────────────────────────────────────────────────────

    async def process_events(
        self,
        user_id: str,
        events: list[dict],
        selected_calendars: list[str] | None = None,
    ) -> dict:
        """
        Process a list of raw calendar events.

        Returns:
          {
            "processed": int,       # events saved as personal
            "filtered": int,        # events dropped (work or not in selected_calendars)
            "life_events_found": int,
            "signals_extracted": int,
          }
        """
        stats = {
            "processed": 0,
            "filtered": 0,
            "life_events_found": 0,
            "signals_extracted": 0,
        }

        for event in events:
            title = event.get("title", "")
            cal_name = event.get("calendar_name", "")

            # ── Calendar selection filter ──────────────────────────────────
            if selected_calendars is not None:
                if cal_name not in selected_calendars:
                    stats["filtered"] += 1
                    continue

            # ── WorkFilter ─────────────────────────────────────────────────
            classify_content = {
                "title": title,
                "description": (event.get("description") or "")[:200],
                "calendar_name": cal_name,
                "attendees": event.get("attendees", []),
            }

            fr = await self._work_filter.classify(
                content_type="calendar",
                content=classify_content,
                user_id=user_id,
            )

            if not fr.passes:
                stats["filtered"] += 1
                continue

            # ── Save to calendar_events ────────────────────────────────────
            try:
                self._save_event(user_id, event, work_filtered=False)
                stats["processed"] += 1
            except Exception as exc:
                logger.warning(f"Failed to save calendar event '{title}': {exc}")
                continue

            # ── Life signal extraction (fire-and-forget) ───────────────────
            try:
                life_result = await self._extract_life_signals(user_id, event)
                stats["life_events_found"] += life_result.get("life_events", 0)
                stats["signals_extracted"] += life_result.get("signals", 0)
            except Exception as exc:
                logger.warning(f"Life signal extraction failed for '{title}': {exc}")

        return stats

    # ── Private helpers ───────────────────────────────────────────────────────

    def _save_event(self, user_id: str, event: dict, work_filtered: bool) -> None:
        """Upsert a calendar event record to the calendar_events table."""
        db.get_db().table("calendar_events").upsert({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": event.get("title", ""),
            "description": (event.get("description") or "")[:1000],
            "start_time": event.get("start_time"),
            "end_time": event.get("end_time") or None,
            "calendar_name": event.get("calendar_name", ""),
            "work_filtered": work_filtered,
            "attendees": event.get("attendees", []),
        }).execute()

    async def _extract_life_signals(self, user_id: str, event: dict) -> dict:
        """
        Extract life signals from a personal calendar event.
        Returns {"life_events": int, "signals": int} for stats tracking.
        """
        title = event.get("title", "")
        start_time = event.get("start_time", "")
        attendees = event.get("attendees", [])
        counts = {"life_events": 0, "signals": 0}

        # ── Birthday / anniversary → life_events table ────────────────────
        if _BIRTHDAY_RE.search(title):
            await self._save_life_event(
                user_id=user_id,
                event_type="birthday",
                description=title,
                approximate_date=start_time[:10] if start_time else None,
            )
            counts["life_events"] += 1

        elif _ANNIVERSARY_RE.search(title):
            await self._save_life_event(
                user_id=user_id,
                event_type="anniversary",
                description=title,
                approximate_date=start_time[:10] if start_time else None,
            )
            counts["life_events"] += 1

        # ── Travel → interest signal ───────────────────────────────────────
        if _TRAVEL_RE.search(title):
            await self._save_interest_signal(
                user_id=user_id,
                category="travel",
                source="calendar",
                note=title,
            )
            counts["signals"] += 1

        # ── Health appointment → health signal ────────────────────────────
        if _HEALTH_RE.search(title):
            await self._increment_capability_signal(
                user_id=user_id,
                capability_area="physical",
                delta=0.05,
                source=f"calendar: {title[:80]}",
            )
            counts["signals"] += 1

        # ── Gym / exercise → physical capability signal ───────────────────
        if _GYM_RE.search(title):
            await self._increment_capability_signal(
                user_id=user_id,
                capability_area="physical",
                delta=0.1,
                source=f"calendar: {title[:80]}",
            )
            counts["signals"] += 1

        # ── Large social gathering → social signal ────────────────────────
        if len(attendees) > 5:
            await self._save_interest_signal(
                user_id=user_id,
                category="social",
                source="calendar",
                note=f"Large event: {title[:80]} ({len(attendees)} attendees)",
            )
            counts["signals"] += 1

        return counts

    async def _save_life_event(
        self,
        user_id: str,
        event_type: str,
        description: str,
        approximate_date: str | None,
    ) -> None:
        """Upsert a life_events record (best-effort)."""
        try:
            db.get_db().table("life_events").insert({
                "id": str(uuid.uuid4()),
                "owner_user_id": user_id,
                "event_type": event_type,
                "description": description[:500],
                "approximate_date": approximate_date,
                "source": "calendar",
            }).execute()
        except Exception as exc:
            logger.debug(f"life_events insert skipped (may be duplicate): {exc}")

    async def _save_interest_signal(
        self,
        user_id: str,
        category: str,
        source: str,
        note: str,
    ) -> None:
        """Add an interest signal to the user's profile (best-effort)."""
        try:
            db.get_db().table("interest_signals").insert({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "category": category,
                "source": source,
                "note": note[:500],
            }).execute()
        except Exception as exc:
            logger.debug(f"interest_signals insert skipped: {exc}")

    async def _increment_capability_signal(
        self,
        user_id: str,
        capability_area: str,
        delta: float,
        source: str,
    ) -> None:
        """Increment a capability signal for the user (best-effort)."""
        try:
            db.get_db().table("capability_signals").insert({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "capability_area": capability_area,
                "delta": delta,
                "source": source[:500],
            }).execute()
        except Exception as exc:
            logger.debug(f"capability_signals insert skipped: {exc}")


# ── Router endpoint ───────────────────────────────────────────────────────────

_processor = ICalendarProcessor()

if _FASTAPI_AVAILABLE:
    @router.post("/calendar/sync")
    async def calendar_sync(body: CalendarSyncRequest) -> dict:
        """
        iOS sends all calendar events here after the user selects which calendars to share.
        Returns a summary of what was processed, filtered, and discovered.
        """
        if not body.user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        # Convert Pydantic models to plain dicts for the processor
        events_raw = [e.model_dump() for e in body.events]

        result = await _processor.process_events(
            user_id=body.user_id,
            events=events_raw,
            selected_calendars=body.selected_calendars,
        )

        return {
            "ok": True,
            "processed": result["processed"],
            "filtered": result["filtered"],
            "life_events_found": result["life_events_found"],
            "signals_extracted": result["signals_extracted"],
            "message": f"Genie read {result['processed']} personal events and found {result['life_events_found']} important moments.",
        }
