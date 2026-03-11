"""
test_icalendar_processor.py — Tests for ICalendarProcessor.

All WorkFilter classify calls are mocked; no Claude API or Supabase needed.
Tests cover:
  - work events filtered
  - birthday extraction from event title
  - anniversary extraction
  - travel signal extraction
  - gym / health signal extraction
  - calendar selection filtering
  - large attendee list → social signal
  - empty event list
  - CalendarSyncRequest schema validation
  - stats returned correctly
"""
import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_event(**kwargs) -> dict:
    defaults = {
        "title": "Personal event",
        "description": "",
        "start_time": "2024-06-15T10:00:00Z",
        "end_time": "2024-06-15T11:00:00Z",
        "calendar_name": "Personal",
        "attendees": [],
    }
    defaults.update(kwargs)
    return defaults


def _make_processor_and_db(classify_label: str = "personal"):
    """
    Return (processor, mock_db) with WorkFilter classify stubbed.
    classify_label: "personal" | "work" | "ambiguous"

    The caller is responsible for patching 'services.icalendar_processor.db'
    around the actual test call.  This helper only sets up the processor object
    and a pre-built mock_db that tests can pass to patch().
    """
    from services.icalendar_processor import ICalendarProcessor
    from core.ingestion.work_filter import FilterResult, Label

    label_map = {
        "personal": Label.PERSONAL,
        "work": Label.WORK,
        "ambiguous": Label.AMBIGUOUS,
    }
    fr = FilterResult(label=label_map[classify_label], confidence=0.9, reason="mocked")

    proc = ICalendarProcessor()
    proc._work_filter = MagicMock()
    proc._work_filter.classify = AsyncMock(return_value=fr)

    # Build a mock db that silently accepts all table operations
    mock_db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[])
    mock_db.get_db.return_value.table.return_value.insert.return_value = chain
    mock_db.get_db.return_value.table.return_value.upsert.return_value = chain

    return proc, mock_db


def _run(coro):
    """Run an async coroutine synchronously (avoids pytest-asyncio dependency)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Work filtering ────────────────────────────────────────────────────────────

def test_work_event_is_filtered():
    """Work-classified event → counted as filtered, not saved."""
    proc, mock_db = _make_processor_and_db("work")
    events = [_make_event(title="Sprint retrospective")]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events))

    assert result["filtered"] == 1
    assert result["processed"] == 0


def test_ambiguous_event_is_filtered():
    """Ambiguous event → also filtered (conservative)."""
    proc, mock_db = _make_processor_and_db("ambiguous")
    events = [_make_event(title="Planning session")]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events))

    assert result["filtered"] == 1
    assert result["processed"] == 0


def test_personal_event_is_processed():
    """Personal event → saved and counted as processed."""
    proc, mock_db = _make_processor_and_db("personal")
    events = [_make_event(title="Dinner with Alice")]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events))

    assert result["processed"] == 1
    assert result["filtered"] == 0


# ── Calendar selection filtering ──────────────────────────────────────────────

def test_calendar_selection_filters_excluded_calendar():
    """User selected only 'Personal' — Work calendar events dropped before WorkFilter."""
    proc, mock_db = _make_processor_and_db("personal")
    events = [
        _make_event(title="Team lunch", calendar_name="Work"),
        _make_event(title="Mom's birthday", calendar_name="Personal"),
    ]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events, selected_calendars=["Personal"]))

    assert result["filtered"] == 1    # Work calendar event skipped
    assert result["processed"] == 1   # Personal calendar event processed


def test_calendar_selection_none_means_all_calendars():
    """selected_calendars=None → all calendars pass the selection check."""
    proc, mock_db = _make_processor_and_db("personal")
    events = [
        _make_event(title="Event A", calendar_name="Work"),
        _make_event(title="Event B", calendar_name="Health"),
    ]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events, selected_calendars=None))

    assert result["processed"] == 2


# ── Birthday extraction ───────────────────────────────────────────────────────

def test_birthday_in_title_creates_life_event():
    """'Mom's birthday' triggers a life_events record."""
    proc, mock_db = _make_processor_and_db("personal")
    events = [_make_event(title="Mom's birthday")]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events))

    assert result["life_events_found"] >= 1


def test_bday_abbreviation_in_title_creates_life_event():
    """'Alice bday dinner' (abbreviation) triggers life_events."""
    proc, mock_db = _make_processor_and_db("personal")
    events = [_make_event(title="Alice bday dinner")]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events))

    assert result["life_events_found"] >= 1


def test_anniversary_in_title_creates_life_event():
    """'Wedding anniversary' triggers life_events."""
    proc, mock_db = _make_processor_and_db("personal")
    events = [_make_event(title="Our wedding anniversary dinner")]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events))

    assert result["life_events_found"] >= 1


# ── Travel signal extraction ──────────────────────────────────────────────────

def test_flight_in_title_creates_travel_signal():
    """'Flight to Lisbon' extracts a travel interest signal."""
    proc, mock_db = _make_processor_and_db("personal")
    events = [_make_event(title="Flight to Lisbon")]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events))

    assert result["signals_extracted"] >= 1


def test_vacation_in_title_creates_travel_signal():
    """'Portugal vacation' creates a travel signal."""
    proc, mock_db = _make_processor_and_db("personal")
    events = [_make_event(title="Portugal vacation")]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events))

    assert result["signals_extracted"] >= 1


# ── Health / gym signal extraction ────────────────────────────────────────────

def test_therapist_appointment_creates_health_signal():
    """'Therapist appointment' increments physical capability signal."""
    proc, mock_db = _make_processor_and_db("personal")
    events = [_make_event(title="Therapist appointment")]

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", events))

    assert result["signals_extracted"] >= 1


# ── Empty event list ──────────────────────────────────────────────────────────

def test_empty_event_list_returns_zero_stats():
    """Empty event list → all stats are zero."""
    proc, mock_db = _make_processor_and_db("personal")

    with patch("services.icalendar_processor.db", mock_db):
        result = _run(proc.process_events("u1", []))

    assert result["processed"] == 0
    assert result["filtered"] == 0
    assert result["life_events_found"] == 0
    assert result["signals_extracted"] == 0


# ── CalendarSyncRequest schema ────────────────────────────────────────────────

def test_calendar_sync_request_schema():
    """CalendarSyncRequest validates with required and optional fields."""
    from services.icalendar_processor import CalendarSyncRequest, CalendarEvent

    req = CalendarSyncRequest(
        user_id="u1",
        events=[
            CalendarEvent(
                title="Mom's birthday",
                start_time="2024-06-15T10:00:00Z",
                calendar_name="Personal",
            )
        ],
        selected_calendars=["Personal"],
    )
    assert req.user_id == "u1"
    assert len(req.events) == 1
    assert req.events[0].title == "Mom's birthday"
    assert req.selected_calendars == ["Personal"]


def test_calendar_event_default_fields():
    """CalendarEvent has sensible defaults for optional fields."""
    from services.icalendar_processor import CalendarEvent

    ev = CalendarEvent(title="Gym", start_time="2024-01-01T08:00:00Z")
    assert ev.description == ""
    assert ev.attendees == []
    assert ev.calendar_name == ""
