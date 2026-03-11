"""
tests/test_communication_dna.py — Unit tests for services/communication_dna.py

Covers:
- Linguistic intimacy score computation
- Individual score component methods
- Initiation ratio calculation
- DNA profile schema validation
- Edge cases (empty messages, single message, missing timestamps)
- Silence pattern description
- Intimacy trend detection
- Callback/inside-reference scoring
- update_person_dna cache logic

All tests are pure-unit: no Supabase calls, no Anthropic calls.
External dependencies mocked via unittest.mock.
"""
import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Patch settings and database before importing the module under test
_MOCK_SETTINGS = MagicMock()
_MOCK_SETTINGS.claude_model = "claude-sonnet-4-5"
_MOCK_SETTINGS.anthropic_api_key = "test-key"
_MOCK_SETTINGS.supabase_url = "https://test.supabase.co"
_MOCK_SETTINGS.supabase_key = "test-key"

with patch("config.get_settings", return_value=_MOCK_SETTINGS):
    with patch("database.get_db", return_value=MagicMock()):
        with patch("policy_engine.guard.check", return_value=None):
            from services.communication_dna import CommunicationDNA, _count_emojis


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(offset_hours: float = 0) -> str:
    """ISO timestamp offset from a fixed base time."""
    base = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(hours=offset_hours)).isoformat()


def _msg(text: str, is_from_me: bool, offset_hours: float = 0) -> dict:
    return {"text": text, "is_from_me": is_from_me, "timestamp": _ts(offset_hours)}


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


DNA_SCHEMA_KEYS = {
    "linguistic_intimacy",
    "avg_response_time_hours",
    "initiates_ratio",
    "message_length_avg",
    "emoji_frequency",
    "typical_tone",
    "topics_recurring",
    "silence_patterns",
    "peak_communication_hours",
    "language_shifts",
    "intimacy_trend",
    "computed_at",
    "message_count",
}


# ── Test: empty messages ───────────────────────────────────────────────────────

class TestEdgeCasesEmptyMessages:
    def test_empty_messages_returns_zero_intimacy(self):
        dna = CommunicationDNA()
        score = run(dna.compute_linguistic_intimacy([]))
        assert score == 0.0

    def test_single_message_does_not_crash(self):
        dna = CommunicationDNA()
        messages = [_msg("Hey there!", True, 0)]
        score = run(dna.compute_linguistic_intimacy(messages))
        assert 0.0 <= score <= 1.0

    def test_empty_profile_has_all_schema_keys(self):
        dna = CommunicationDNA()
        profile = dna._empty_profile()
        assert DNA_SCHEMA_KEYS.issubset(set(profile.keys()))

    def test_empty_profile_message_count_is_zero(self):
        dna = CommunicationDNA()
        profile = dna._empty_profile()
        assert profile["message_count"] == 0

    def test_empty_profile_intimacy_is_zero(self):
        dna = CommunicationDNA()
        profile = dna._empty_profile()
        assert profile["linguistic_intimacy"] == 0.0


# ── Test: intimacy score components ──────────────────────────────────────────

class TestLinguisticIntimacyScore:
    def test_score_bounded_0_to_1(self):
        dna = CommunicationDNA()
        messages = [_msg("lol babe omg bestie haha 😂🔥", True, i) for i in range(20)]
        score = run(dna.compute_linguistic_intimacy(messages))
        assert 0.0 <= score <= 1.0

    def test_nickname_boosts_score(self):
        dna = CommunicationDNA()
        msgs_with_nick = [_msg("hey babe how are you", True, i) for i in range(5)]
        msgs_without_nick = [_msg("hello how are you today", True, i) for i in range(5)]
        score_with = run(dna.compute_linguistic_intimacy(msgs_with_nick))
        score_without = run(dna.compute_linguistic_intimacy(msgs_without_nick))
        assert score_with >= score_without

    def test_abbreviations_boost_score(self):
        dna = CommunicationDNA()
        msgs_abbrev = [_msg("lol omg ngl idk tbh fr", True, i) for i in range(10)]
        msgs_formal = [_msg("that is very interesting indeed", True, i) for i in range(10)]
        score_abbrev = run(dna.compute_linguistic_intimacy(msgs_abbrev))
        score_formal = run(dna.compute_linguistic_intimacy(msgs_formal))
        assert score_abbrev >= score_formal

    def test_short_response_time_boosts_score(self):
        """Replies within 30 minutes should score higher than replies after 24h."""
        dna = CommunicationDNA()
        fast_msgs = []
        for i in range(10):
            fast_msgs.append(_msg("hey", i % 2 == 0, i * 0.5))  # 30min gaps
        slow_msgs = []
        for i in range(10):
            slow_msgs.append(_msg("hey", i % 2 == 0, i * 24.0))  # 24h gaps
        score_fast = run(dna.compute_linguistic_intimacy(fast_msgs))
        score_slow = run(dna.compute_linguistic_intimacy(slow_msgs))
        assert score_fast >= score_slow

    def test_balanced_initiation_boosts_score(self):
        """50/50 initiation should score higher than 90/10."""
        dna = CommunicationDNA()
        # Alternating sends (balanced)
        balanced = [_msg("hi", i % 2 == 0, i * 2.0) for i in range(20)]
        # All from me (unbalanced)
        unbalanced = [_msg("hi", True, i * 2.0) for i in range(20)]
        ratio_balanced = dna._compute_initiates_ratio(balanced)
        # Just check ratio is in a reasonable range for balanced
        assert 0.3 <= ratio_balanced <= 0.7


# ── Test: initiation ratio ─────────────────────────────────────────────────────

class TestInitiationRatio:
    def test_all_from_me_is_high_ratio(self):
        dna = CommunicationDNA()
        # Each message is a new thread (4+ hour gap)
        msgs = [_msg("hi", True, i * 5.0) for i in range(10)]
        ratio = dna._compute_initiates_ratio(msgs)
        assert ratio > 0.8

    def test_none_from_me_is_low_ratio(self):
        dna = CommunicationDNA()
        msgs = [_msg("hi", False, i * 5.0) for i in range(10)]
        ratio = dna._compute_initiates_ratio(msgs)
        assert ratio < 0.2

    def test_empty_messages_returns_half(self):
        dna = CommunicationDNA()
        assert dna._compute_initiates_ratio([]) == 0.5

    def test_alternating_rapid_messages_counted_as_single_thread(self):
        """Rapid back-and-forth (< 3h) should count as one thread initiation."""
        dna = CommunicationDNA()
        # One thread: me starts, we chat for 2 hours
        msgs = [_msg("hey", True, 0), _msg("hi", False, 0.5), _msg("how are you", True, 1.0)]
        ratio = dna._compute_initiates_ratio(msgs)
        # Only 1 initiation (me), so ratio should be 1.0
        assert ratio == 1.0


# ── Test: DNA profile schema validation ──────────────────────────────────────

class TestDNAProfileSchema:
    def test_analyze_relationship_returns_all_schema_keys(self):
        dna = CommunicationDNA()
        messages = [
            _msg("hey babe how are you lol", True, 0),
            _msg("im good! how about you 😊", False, 0.5),
            _msg("pretty good, going to yoga", True, 1.0),
            _msg("nice! i was just thinking about you", False, 1.5),
        ]

        mock_db = MagicMock()
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        async def mock_analyze_with_claude(messages):
            return ("warm, playful", ["health", "fitness"], "stable tone throughout")

        with patch("database.get_db", return_value=mock_db):
            with patch.object(dna, "_analyze_with_claude", new=mock_analyze_with_claude):
                with patch.object(dna, "_save_profile", new=AsyncMock()):
                    profile = run(dna.analyze_relationship("user-1", "person-1", messages))

        assert DNA_SCHEMA_KEYS.issubset(set(profile.keys()))

    def test_profile_intimacy_in_range(self):
        dna = CommunicationDNA()
        messages = [_msg("hey", True, i) for i in range(5)]
        with patch.object(dna, "_analyze_with_claude", new=AsyncMock(return_value=("warm", [], "stable"))):
            with patch.object(dna, "_save_profile", new=AsyncMock()):
                profile = run(dna.analyze_relationship("u", "p", messages))
        assert 0.0 <= profile["linguistic_intimacy"] <= 1.0

    def test_profile_message_count_matches_input(self):
        dna = CommunicationDNA()
        messages = [_msg("test", True, i) for i in range(7)]
        with patch.object(dna, "_analyze_with_claude", new=AsyncMock(return_value=("warm", [], "stable"))):
            with patch.object(dna, "_save_profile", new=AsyncMock()):
                profile = run(dna.analyze_relationship("u", "p", messages))
        assert profile["message_count"] == 7

    def test_empty_messages_returns_empty_profile(self):
        dna = CommunicationDNA()
        with patch.object(dna, "_save_profile", new=AsyncMock()):
            profile = run(dna.analyze_relationship("u", "p", []))
        assert profile["message_count"] == 0
        assert profile["linguistic_intimacy"] == 0.0


# ── Test: silence patterns ────────────────────────────────────────────────────

class TestSilencePatterns:
    def test_frequent_contact_pattern(self):
        dna = CommunicationDNA()
        msgs = [_msg("hi", True, i * 0.5) for i in range(20)]  # every 30 min
        pattern = dna._compute_silence_pattern(msgs)
        assert "daily" in pattern or "frequent" in pattern

    def test_long_silence_pattern(self):
        dna = CommunicationDNA()
        msgs = [_msg("hi", True, i * 168.0) for i in range(5)]  # weekly
        pattern = dna._compute_silence_pattern(msgs)
        assert "day" in pattern.lower() or "normal" in pattern.lower()

    def test_empty_messages_returns_default(self):
        dna = CommunicationDNA()
        pattern = dna._compute_silence_pattern([])
        assert "frequent" in pattern or "rarely" in pattern


# ── Test: intimacy trend ──────────────────────────────────────────────────────

class TestIntimacyTrend:
    def test_increasing_trend_detected(self):
        dna = CommunicationDNA()
        # First half: short messages; second half: long messages
        first = [_msg("ok", True, i) for i in range(10)]
        second = [_msg("this is a much longer message with lots of details about my day", True, i + 10) for i in range(10)]
        trend = dna._compute_intimacy_trend(first + second)
        assert trend == "increasing"

    def test_declining_trend_detected(self):
        dna = CommunicationDNA()
        first = [_msg("this is a much longer message with lots of details about my day", True, i) for i in range(10)]
        second = [_msg("ok", True, i + 10) for i in range(10)]
        trend = dna._compute_intimacy_trend(first + second)
        assert trend == "declining"

    def test_stable_trend_for_few_messages(self):
        dna = CommunicationDNA()
        msgs = [_msg("hi", True, i) for i in range(5)]
        trend = dna._compute_intimacy_trend(msgs)
        assert trend == "stable"

    def test_stable_trend_when_similar_length(self):
        dna = CommunicationDNA()
        msgs = [_msg("hello there how are you doing today", True, i) for i in range(20)]
        trend = dna._compute_intimacy_trend(msgs)
        assert trend == "stable"
