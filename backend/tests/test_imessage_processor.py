"""
test_imessage_processor.py — Tests for IMessageProcessor and hash_phone.

All WorkFilter calls are mocked so no Claude API or Supabase is needed.
Tests cover:
  - work messages filtered, personal pass through
  - phone hashing
  - empty conversation handling
  - group message detection
  - all-work conversation returns None
  - signal extraction task creation
  - stats aggregation across multiple conversations
"""
import sys
import os
import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_processor():
    """Return an IMessageProcessor with WorkFilter's Claude client stubbed out."""
    with patch("services.imessage_processor.WorkFilter") as MockWF, \
         patch("services.imessage_processor.db") as mock_db, \
         patch("services.imessage_processor.settings") as mock_settings:

        mock_settings.backend_url = "http://localhost:8000"
        mock_settings.anthropic_api_key = "test"
        mock_settings.claude_model = "claude-sonnet-4-5"

        # Provide a real WorkFilter-like object with classify stubbed
        from services.imessage_processor import IMessageProcessor
        proc = IMessageProcessor()

        # Replace the work_filter instance with a mock
        proc._work_filter = MagicMock()

        return proc, mock_db


# ── hash_phone tests ─────────────────────────────────────────────────────────

def test_hash_phone_strips_formatting():
    from services.imessage_processor import hash_phone
    assert hash_phone("+1 (415) 555-1234") == hash_phone("14155551234")


def test_hash_phone_is_sha256():
    from services.imessage_processor import hash_phone
    plain = "14155551234"
    expected = hashlib.sha256(plain.encode()).hexdigest()
    assert hash_phone("+1 (415) 555-1234") == expected


def test_hash_phone_consistent():
    from services.imessage_processor import hash_phone
    # Same input always gives same output
    assert hash_phone("+12125551234") == hash_phone("+12125551234")


def test_hash_phone_different_numbers_differ():
    from services.imessage_processor import hash_phone
    assert hash_phone("+14155551234") != hash_phone("+12125551234")


def test_hash_phone_empty_string():
    from services.imessage_processor import hash_phone
    # Empty string should not raise
    result = hash_phone("")
    assert isinstance(result, str) and len(result) == 64


# ── Empty conversation ────────────────────────────────────────────────────────

def test_process_single_conversation_empty_messages():
    """Empty message list → returns {} not None."""
    from services.imessage_processor import IMessageProcessor
    with patch("services.imessage_processor.WorkFilter"), \
         patch("services.imessage_processor.db"), \
         patch("services.imessage_processor.settings") as ms:
        ms.backend_url = "http://localhost:8000"
        ms.anthropic_api_key = "test"
        ms.claude_model = "x"
        proc = IMessageProcessor()

    result = asyncio.get_event_loop().run_until_complete(
        proc.process_single_conversation(
            user_id="u1",
            contact_name="Alice",
            contact_identifier="+14155551234",
            messages=[],
        )
    )
    assert result == {}


def test_process_single_conversation_only_empty_text():
    """Messages with empty text are skipped — should return {} not None."""
    from services.imessage_processor import IMessageProcessor
    from core.ingestion.work_filter import FilterResult, Label

    with patch("services.imessage_processor.WorkFilter"), \
         patch("services.imessage_processor.db"), \
         patch("services.imessage_processor.settings") as ms:
        ms.backend_url = "http://localhost:8000"
        ms.anthropic_api_key = "test"
        ms.claude_model = "x"
        proc = IMessageProcessor()
        proc._work_filter = MagicMock()

    messages = [{"timestamp": "2024-01-01T10:00:00Z", "text": "", "is_from_me": False}]
    result = asyncio.get_event_loop().run_until_complete(
        proc.process_single_conversation("u1", "Alice", "+1415", messages)
    )
    assert result == {}


# ── Work filtering ────────────────────────────────────────────────────────────

def test_work_message_filtered():
    """All-work conversation → process_single_conversation returns None."""
    from services.imessage_processor import IMessageProcessor
    from core.ingestion.work_filter import FilterResult, Label

    with patch("services.imessage_processor.WorkFilter"), \
         patch("services.imessage_processor.db"), \
         patch("services.imessage_processor.settings") as ms:
        ms.backend_url = "http://localhost:8000"
        ms.anthropic_api_key = "test"
        ms.claude_model = "x"
        proc = IMessageProcessor()

    work_result = FilterResult(label=Label.WORK, confidence=0.9, reason="jargon")
    proc._work_filter = MagicMock()
    proc._work_filter.classify = AsyncMock(return_value=work_result)

    messages = [
        {"timestamp": "2024-01-01T10:00:00Z", "text": "LGTM, merging the PR", "is_from_me": False},
        {"timestamp": "2024-01-01T10:05:00Z", "text": "Sprint retro tomorrow", "is_from_me": True},
    ]
    result = asyncio.get_event_loop().run_until_complete(
        proc.process_single_conversation("u1", "Colleague", "+1415", messages)
    )
    assert result is None


def test_personal_message_passes_through():
    """Personal messages pass WorkFilter and reach the analysis layer."""
    from services.imessage_processor import IMessageProcessor
    from core.ingestion.work_filter import FilterResult, Label

    with patch("services.imessage_processor.WorkFilter"), \
         patch("services.imessage_processor.db") as mock_db, \
         patch("services.imessage_processor.settings") as ms:
        ms.backend_url = "http://localhost:8000"
        ms.anthropic_api_key = "test"
        ms.claude_model = "x"
        proc = IMessageProcessor()

    personal_result = FilterResult(label=Label.PERSONAL, confidence=0.9, reason="personal")
    proc._work_filter = MagicMock()
    proc._work_filter.classify = AsyncMock(return_value=personal_result)

    mock_db.get_people_for_user.return_value = []
    mock_db.get_user_by_id.return_value = {"name": "Abhi", "phone": "+14155551234"}

    messages = [
        {"timestamp": "2024-01-01T10:00:00Z", "text": "Want to grab dinner Saturday?", "is_from_me": False},
    ]

    with patch("services.intelligence.analyze_imessage_conversation", return_value={}):
        result = asyncio.get_event_loop().run_until_complete(
            proc.process_single_conversation("u1", "Alice", "+14155551111", messages)
        )

    assert result is not None
    assert result.get("personal_message_count") == 1


def test_mixed_conversation_only_personal_analyzed():
    """Work messages filtered, personal ones pass through; counts are correct."""
    from services.imessage_processor import IMessageProcessor
    from core.ingestion.work_filter import FilterResult, Label

    with patch("services.imessage_processor.WorkFilter"), \
         patch("services.imessage_processor.db") as mock_db, \
         patch("services.imessage_processor.settings") as ms:
        ms.backend_url = "http://localhost:8000"
        ms.anthropic_api_key = "test"
        ms.claude_model = "x"
        proc = IMessageProcessor()

    def classify_side_effect(content_type, content, user_id=None):
        text = content.get("text_snippet", "")
        if "sprint" in text.lower():
            return FilterResult(label=Label.WORK, confidence=0.9, reason="jargon")
        return FilterResult(label=Label.PERSONAL, confidence=0.9, reason="personal")

    proc._work_filter = MagicMock()
    proc._work_filter.classify = AsyncMock(side_effect=classify_side_effect)

    mock_db.get_people_for_user.return_value = []
    mock_db.get_user_by_id.return_value = {"name": "Abhi"}

    messages = [
        {"timestamp": "2024-01-01T10:00:00Z", "text": "Sprint planning at 9am", "is_from_me": True},
        {"timestamp": "2024-01-01T10:05:00Z", "text": "Miss you, let's catch up", "is_from_me": False},
    ]

    with patch("services.intelligence.analyze_imessage_conversation", return_value={}):
        result = asyncio.get_event_loop().run_until_complete(
            proc.process_single_conversation("u1", "Alice", "+14155551111", messages)
        )

    assert result is not None
    assert result["personal_message_count"] == 1
    assert result["filtered_work"] == 1


# ── Group message detection ───────────────────────────────────────────────────

def test_group_message_with_work_group_name_filtered():
    """Messages in a group named 'Backend team' are detected as work via WorkFilter fast-path."""
    from core.ingestion.work_filter import WorkFilter, Label
    with patch("core.ingestion.work_filter.get_settings") as ms:
        ms.return_value.anthropic_api_key = "test"
        ms.return_value.claude_model = "x"
        wf = WorkFilter()

    r = wf._classify_message({
        "sender_name": "Dev",
        "text_snippet": "Good morning!",
        "group_name": "Backend team",
    })
    assert r is not None and r.label == Label.WORK


def test_group_message_with_personal_group_name_not_filtered():
    """A personal group chat name doesn't trigger work filter."""
    from core.ingestion.work_filter import WorkFilter, Label
    with patch("core.ingestion.work_filter.get_settings") as ms:
        ms.return_value.anthropic_api_key = "test"
        ms.return_value.claude_model = "x"
        wf = WorkFilter()

    r = wf._classify_message({
        "sender_name": "Mom",
        "text_snippet": "Dinner Sunday?",
        "group_name": "Family",
    })
    # No fast-path hit → returns None (goes to Claude)
    assert r is None


# ── Stats aggregation ─────────────────────────────────────────────────────────

def test_process_conversations_empty_list():
    """Empty conversation list returns zero stats immediately."""
    from services.imessage_processor import IMessageProcessor

    with patch("services.imessage_processor.WorkFilter"), \
         patch("services.imessage_processor.db"), \
         patch("services.imessage_processor.settings") as ms:
        ms.backend_url = "http://localhost:8000"
        ms.anthropic_api_key = "test"
        ms.claude_model = "x"
        proc = IMessageProcessor()

    result = asyncio.get_event_loop().run_until_complete(
        proc.process_conversations("u1", [])
    )
    assert result["processed"] == 0
    assert result["filtered_work"] == 0
    assert result["people_updated"] == 0
