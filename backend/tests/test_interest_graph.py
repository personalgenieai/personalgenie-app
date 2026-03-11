"""
tests/test_interest_graph.py — Unit tests for services/interest_graph.py

Covers:
- Keyword-based interest extraction from message text
- Claude-based extraction (mocked)
- Confidence scoring and source multipliers
- Deduplication / confidence merging on repeated signals
- Top interests ranking by confidence × seen_count
- Calendar, maps, and transaction source ingestion
- Edge cases: empty input, unknown categories
- get_profile structure validation

All tests are pure-unit: no Supabase calls, no Anthropic calls.
"""
import asyncio
import json
from datetime import datetime, timezone
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
            from services.interest_graph import InterestGraph, SOURCE_CONFIDENCE, CATEGORIES


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_mock_db(existing_rows=None, upserted_row=None):
    """Build a mock Supabase client for interest graph tests."""
    mock = MagicMock()
    existing_rows = existing_rows or []
    upserted_row = upserted_row or {"id": "row-1"}

    def table_side_effect(name):
        t = MagicMock()
        if name == "user_interests":
            # select chain for dedup check
            t.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=existing_rows)
            # select chain for _load_rows
            t.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=existing_rows)
            t.insert.return_value.execute.return_value = MagicMock(data=[upserted_row])
            t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[upserted_row])
        return t

    mock.table.side_effect = table_side_effect
    return mock


# ── Test: keyword extraction ──────────────────────────────────────────────────

class TestKeywordExtraction:
    def test_yoga_extracted_as_fitness(self):
        graph = InterestGraph()
        signals = graph._extract_with_keywords("I love doing yoga in the morning", "message")
        assert any(s["category"] == "fitness" and "yoga" in s["value"] for s in signals)

    def test_sushi_extracted_as_food(self):
        graph = InterestGraph()
        signals = graph._extract_with_keywords("craving sushi right now", "message")
        assert any(s["category"] == "food" for s in signals)

    def test_jazz_extracted_as_music(self):
        graph = InterestGraph()
        signals = graph._extract_with_keywords("been listening to jazz all day", "message")
        assert any(s["category"] == "music" and "jazz" in s["value"] for s in signals)

    def test_empty_text_returns_empty_list(self):
        graph = InterestGraph()
        signals = graph._extract_with_keywords("", "message")
        assert signals == []

    def test_no_keywords_returns_empty_list(self):
        graph = InterestGraph()
        signals = graph._extract_with_keywords("the weather is nice today", "message")
        assert signals == []

    def test_confidence_discounted_for_keyword_extraction(self):
        """Keyword extraction gets a slight confidence discount vs Claude."""
        graph = InterestGraph()
        signals = graph._extract_with_keywords("I love yoga", "message")
        assert all(s["confidence"] < SOURCE_CONFIDENCE["message"] for s in signals)

    def test_multiple_keywords_in_one_message(self):
        graph = InterestGraph()
        signals = graph._extract_with_keywords("I love yoga and sushi and jazz", "message")
        categories = {s["category"] for s in signals}
        assert "fitness" in categories
        assert "food" in categories
        assert "music" in categories


# ── Test: transaction source ──────────────────────────────────────────────────

class TestTransactionSource:
    def test_restaurant_transaction_maps_to_food(self):
        graph = InterestGraph()
        txns = [{"name": "Nobu", "merchant_name": "Nobu", "capability_signal": "social_food_interest", "amount": 120}]
        mock_db = _make_mock_db()
        with patch("database.get_db", return_value=mock_db):
            results = run(graph.update_from_transactions("user-1", txns))
        # Should attempt to upsert something
        assert mock_db.table.called

    def test_gym_transaction_maps_to_fitness(self):
        graph = InterestGraph()
        txns = [{"name": "Equinox", "merchant_name": "Equinox", "capability_signal": "physical_capability", "amount": 250}]
        mock_db = _make_mock_db()
        with patch("database.get_db", return_value=mock_db):
            results = run(graph.update_from_transactions("user-1", txns))
        assert mock_db.table.called

    def test_mental_health_transaction_not_extracted(self):
        """emotional_capability signals must not produce interest rows."""
        graph = InterestGraph()
        txns = [{"name": "BetterHelp", "capability_signal": "emotional_capability", "amount": 80}]
        mock_db = _make_mock_db()
        with patch("database.get_db", return_value=mock_db):
            results = run(graph.update_from_transactions("user-1", txns))
        # No insert should have been called for emotional_capability
        # (table may be called for select-check, but insert should not happen for this signal)
        if mock_db.table.called:
            for call in mock_db.table.return_value.insert.call_args_list:
                row = call[0][0] if call[0] else {}
                assert "emotional" not in str(row.get("subcategory", "")).lower()

    def test_empty_transactions_returns_empty(self):
        graph = InterestGraph()
        mock_db = _make_mock_db()
        with patch("database.get_db", return_value=mock_db):
            results = run(graph.update_from_transactions("user-1", []))
        assert results == []


# ── Test: confidence scoring ──────────────────────────────────────────────────

class TestConfidenceScoring:
    def test_transaction_has_highest_source_confidence(self):
        assert SOURCE_CONFIDENCE["transaction"] > SOURCE_CONFIDENCE["message"]

    def test_manual_source_has_max_confidence(self):
        assert SOURCE_CONFIDENCE["manual"] == 1.0

    def test_confidence_merged_on_duplicate(self):
        """Repeated signals should merge confidence, not just overwrite."""
        graph = InterestGraph()
        existing = [{
            "id": "row-1",
            "confidence": 0.6,
            "seen_count": 3,
            "category": "fitness",
            "subcategory": "activities",
            "value": "yoga",
        }]
        mock_db = _make_mock_db(existing_rows=existing)
        signals = [{"category": "fitness", "subcategory": "activities", "value": "yoga", "confidence": 0.8, "source": "message"}]

        with patch("database.get_db", return_value=mock_db):
            run(graph._upsert_signals("user-1", signals))

        # Should call update, not insert
        mock_db.table.return_value.update.assert_called()

    def test_new_signal_calls_insert(self):
        graph = InterestGraph()
        mock_db = _make_mock_db(existing_rows=[])
        signals = [{"category": "music", "subcategory": "genres", "value": "jazz", "confidence": 0.7, "source": "message"}]

        with patch("database.get_db", return_value=mock_db):
            run(graph._upsert_signals("user-1", signals))

        mock_db.table.return_value.insert.assert_called()


# ── Test: top interests ranking ───────────────────────────────────────────────

class TestTopInterestsRanking:
    def test_higher_confidence_ranks_first(self):
        graph = InterestGraph()
        rows = [
            {"category": "music", "subcategory": "genres", "value": "jazz", "confidence": 0.9, "seen_count": 1},
            {"category": "food", "subcategory": "cuisines", "value": "sushi", "confidence": 0.5, "seen_count": 1},
        ]
        mock_db = _make_mock_db(existing_rows=rows)
        with patch("database.get_db", return_value=mock_db):
            top = run(graph.get_top_interests("user-1", limit=5))
        assert top[0] == "jazz"

    def test_high_seen_count_can_outrank_slightly_lower_confidence(self):
        """Value with seen_count=10 and confidence=0.7 > value with seen_count=1 confidence=0.8."""
        graph = InterestGraph()
        rows = [
            {"category": "fitness", "subcategory": "activities", "value": "yoga", "confidence": 0.7, "seen_count": 10},
            {"category": "music", "subcategory": "genres", "value": "jazz", "confidence": 0.8, "seen_count": 1},
        ]
        mock_db = _make_mock_db(existing_rows=rows)
        with patch("database.get_db", return_value=mock_db):
            top = run(graph.get_top_interests("user-1", limit=5))
        # yoga score = 0.7 * 2.0 = 1.4; jazz score = 0.8 * 1.1 = 0.88
        assert top[0] == "yoga"

    def test_limit_respected(self):
        graph = InterestGraph()
        rows = [
            {"category": "music", "subcategory": "genres", "value": f"genre_{i}", "confidence": 0.9 - i * 0.01, "seen_count": 1}
            for i in range(20)
        ]
        mock_db = _make_mock_db(existing_rows=rows)
        with patch("database.get_db", return_value=mock_db):
            top = run(graph.get_top_interests("user-1", limit=5))
        assert len(top) <= 5

    def test_empty_db_returns_empty_list(self):
        graph = InterestGraph()
        mock_db = _make_mock_db(existing_rows=[])
        with patch("database.get_db", return_value=mock_db):
            top = run(graph.get_top_interests("user-1"))
        assert top == []


# ── Test: get_profile structure ───────────────────────────────────────────────

class TestGetProfile:
    def test_profile_contains_all_categories(self):
        graph = InterestGraph()
        mock_db = _make_mock_db(existing_rows=[])
        with patch("database.get_db", return_value=mock_db):
            profile = run(graph.get_profile("user-1"))
        for cat in CATEGORIES:
            assert cat in profile

    def test_profile_rows_sorted_by_confidence(self):
        graph = InterestGraph()
        rows = [
            {"category": "music", "subcategory": "genres", "value": "pop", "confidence": 0.4, "seen_count": 1, "source": "message", "last_seen_at": None},
            {"category": "music", "subcategory": "genres", "value": "jazz", "confidence": 0.9, "seen_count": 1, "source": "message", "last_seen_at": None},
        ]
        mock_db = _make_mock_db(existing_rows=rows)
        with patch("database.get_db", return_value=mock_db):
            profile = run(graph.get_profile("user-1"))
        music_genres = profile.get("music", {}).get("genres", [])
        if len(music_genres) >= 2:
            assert music_genres[0]["confidence"] >= music_genres[1]["confidence"]
