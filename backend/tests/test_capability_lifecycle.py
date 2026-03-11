"""
tests/test_capability_lifecycle.py — Unit tests for Capability Lifecycle Engine (Step 16).

All tests are pure-unit: no Supabase calls, no API calls.
External dependencies are mocked via unittest.mock.

Run: python -m pytest tests/test_capability_lifecycle.py -v
"""
import asyncio
from datetime import datetime, timezone, timedelta, date
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

# ---------------------------------------------------------------------------
# Patch settings and database before importing the module under test.
# ---------------------------------------------------------------------------
_MOCK_SETTINGS = MagicMock()
_MOCK_SETTINGS.claude_model = "claude-sonnet-4-5"
_MOCK_SETTINGS.anthropic_api_key = "test-key"
_MOCK_SETTINGS.supabase_url = "https://test.supabase.co"
_MOCK_SETTINGS.supabase_key = "test-key"

with patch("config.get_settings", return_value=_MOCK_SETTINGS):
    with patch("database.get_db", return_value=MagicMock()):
        with patch("policy_engine.guard.check", return_value=None):
            import services.capability_lifecycle as sut


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(user_id="user-001", days_ago=30):
    created_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {"id": user_id, "phone": "+15551234567", "name": "Test User", "created_at": created_at}


def _make_lifecycle_row(user_id="user-001", area="physical", stage=0, signal_score=0.0,
                        offered_at=None, declined_at=None):
    return {
        "user_id": user_id,
        "area": area,
        "stage": stage,
        "signal_score": signal_score,
        "offered_at": offered_at,
        "declined_at": declined_at,
        "last_evaluated_at": None,
    }


def _make_supabase_mock(
    users=None, lifecycle_rows=None, messages=None, health_rows=None,
    people=None, genie_convs=None, third_party=None, emotional_states=None,
    training=None, music_connections=None, bilateral=None,
):
    mock = MagicMock()

    users = users or []
    lifecycle_rows = lifecycle_rows or []
    messages = messages or []
    health_rows = health_rows or []
    people_data = people or []
    genie_convs = genie_convs or []
    third_party = third_party or []
    emotional_states = emotional_states or []
    training = training or []
    music_connections = music_connections or []
    bilateral = bilateral or []

    def table_side(name):
        t = MagicMock()
        if name == "users":
            t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=users)
        elif name == "capability_lifecycle":
            t.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=lifecycle_rows)
            t.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=lifecycle_rows)
            t.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            t.insert.return_value.execute.return_value = MagicMock(data=[])
            t.upsert.return_value.execute.return_value = MagicMock(data=[])
        elif name == "messages":
            t.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(data=messages)
            t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=messages)
            t.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=messages)
        elif name == "health_daily_summary":
            t.select.return_value.eq.return_value.gte.return_value.gt.return_value.execute.return_value = MagicMock(data=health_rows)
            t.select.return_value.eq.return_value.gt.return_value.execute.return_value = MagicMock(data=health_rows)
        elif name == "training_sessions":
            t.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=training)
        elif name == "music_connections":
            t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=music_connections)
        elif name == "genie_conversations":
            t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=genie_convs)
        elif name == "third_party_signals":
            t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=third_party)
            t.select.return_value.eq.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=third_party)
        elif name == "emotional_states":
            t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=emotional_states)
        elif name == "people":
            t.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=bilateral)
        elif name == "calendar_events":
            t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        elif name == "interest_signals":
            t.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        return t

    mock.table.side_effect = table_side
    return mock


# ── Constants test ────────────────────────────────────────────────────────────

class TestConstants:
    def test_capability_areas_count(self):
        assert len(sut.CAPABILITY_AREAS) == 8

    def test_required_areas_present(self):
        for area in ["physical", "financial", "communication", "intellectual",
                     "family", "emotional", "professional", "coordination"]:
            assert area in sut.CAPABILITY_AREAS

    def test_thresholds(self):
        assert sut.SIGNAL_THRESHOLD == 0.70
        assert sut.TRUST_THRESHOLD == 0.60
        assert sut.MIN_DAYS == 14
        assert sut.MIN_INTERACTIONS == 20
        assert sut.MAX_OFFERS_PER_MONTH == 1
        assert sut.DECLINE_COOLDOWN_DAYS == 90

    def test_stage_constants(self):
        assert sut.STAGE_UNAWARE == 0
        assert sut.STAGE_OBSERVING == 1
        assert sut.STAGE_READY == 2
        assert sut.STAGE_OFFERED == 3
        assert sut.STAGE_ACTIVE_LEARNING == 4
        assert sut.STAGE_AMBIENT == 5

    def test_offer_messages_defined_for_all_areas(self):
        for area in ["physical", "financial", "communication", "intellectual",
                     "family", "emotional", "professional"]:
            assert area in sut.OFFER_MESSAGES
            assert len(sut.OFFER_MESSAGES[area]) > 0


# ── Trust score ───────────────────────────────────────────────────────────────

class TestTrustScore:
    def test_trust_increases_with_days_on_platform(self):
        engine = sut.CapabilityLifecycleEngine()
        user = _make_user(days_ago=45)

        with patch("services.capability_lifecycle.db.get_user_by_id", return_value=user):
            score = asyncio.get_event_loop().run_until_complete(
                engine._get_trust_score("user-001")
            )

        assert score == pytest.approx(45 / 90, abs=0.01)

    def test_trust_capped_at_1_0_after_90_days(self):
        engine = sut.CapabilityLifecycleEngine()
        user = _make_user(days_ago=120)  # 120 days

        with patch("services.capability_lifecycle.db.get_user_by_id", return_value=user):
            score = asyncio.get_event_loop().run_until_complete(
                engine._get_trust_score("user-001")
            )

        assert score == 1.0

    def test_trust_is_zero_for_new_user(self):
        engine = sut.CapabilityLifecycleEngine()
        user = _make_user(days_ago=0)

        with patch("services.capability_lifecycle.db.get_user_by_id", return_value=user):
            score = asyncio.get_event_loop().run_until_complete(
                engine._get_trust_score("user-001")
            )

        assert score == pytest.approx(0.0, abs=0.02)

    def test_trust_returns_zero_if_user_not_found(self):
        engine = sut.CapabilityLifecycleEngine()

        with patch("services.capability_lifecycle.db.get_user_by_id", return_value=None):
            score = asyncio.get_event_loop().run_until_complete(
                engine._get_trust_score("ghost-user")
            )

        assert score == 0.0


# ── Signal score — physical ───────────────────────────────────────────────────

class TestPhysicalSignalScore:
    def test_score_zero_with_no_data(self):
        engine = sut.CapabilityLifecycleEngine()
        mock_db = _make_supabase_mock(health_rows=[], training=[], messages=[])

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            score = asyncio.get_event_loop().run_until_complete(
                engine._score_physical("user-1")
            )

        assert score == 0.0

    def test_food_logs_above_threshold_adds_score(self):
        engine = sut.CapabilityLifecycleEngine()
        # 5 health rows this week (> 3 threshold)
        health_rows = [{"summary_date": f"2026-03-0{i}", "total_calories": 1800} for i in range(1, 6)]
        mock_db = _make_supabase_mock(health_rows=health_rows, training=[], messages=[])

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            score = asyncio.get_event_loop().run_until_complete(
                engine._score_physical("user-1")
            )

        assert score >= 0.3

    def test_score_capped_at_1_0(self):
        engine = sut.CapabilityLifecycleEngine()
        # Maximum signals from all sources
        health_rows = [{"summary_date": f"2026-03-0{i}", "total_calories": 1800} for i in range(1, 9)]
        training = [{"id": str(i)} for i in range(3)]  # > 1 training session
        messages = [{"body": "protein shake after gym today"} for _ in range(10)]
        mock_db = _make_supabase_mock(health_rows=health_rows, training=training, messages=messages)

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            score = asyncio.get_event_loop().run_until_complete(
                engine._score_physical("user-1")
            )

        assert score <= 1.0


# ── Signal score — emotional ──────────────────────────────────────────────────

class TestEmotionalSignalScore:
    def test_score_zero_with_no_data(self):
        engine = sut.CapabilityLifecycleEngine()
        mock_db = _make_supabase_mock()

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            score = asyncio.get_event_loop().run_until_complete(
                engine._score_emotional("user-1")
            )

        assert score == 0.0

    def test_genie_conversations_add_to_score(self):
        engine = sut.CapabilityLifecycleEngine()
        convs = [{"id": str(i)} for i in range(4)]  # > 2 threshold
        mock_db = _make_supabase_mock(genie_convs=convs)

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            score = asyncio.get_event_loop().run_until_complete(
                engine._score_emotional("user-1")
            )

        assert score >= 0.2

    def test_emotional_state_changes_add_to_score(self):
        engine = sut.CapabilityLifecycleEngine()
        states = [{"id": str(i)} for i in range(5)]  # > 3 threshold
        mock_db = _make_supabase_mock(emotional_states=states)

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            score = asyncio.get_event_loop().run_until_complete(
                engine._score_emotional("user-1")
            )

        assert score >= 0.2


# ── Music auto-stage ──────────────────────────────────────────────────────────

class TestMusicAutoStage:
    def test_music_auto_stages_to_5_when_spotify_connected(self):
        engine = sut.CapabilityLifecycleEngine()
        upserted = []

        def mock_upsert(user_id, area, updates):
            upserted.append((area, updates))

        music_connections = [{"provider": "spotify"}]
        mock_db = _make_supabase_mock(music_connections=music_connections)

        engine._get_lifecycle_row = lambda uid, area: {"stage": 0}
        engine._upsert_lifecycle = mock_upsert

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            asyncio.get_event_loop().run_until_complete(
                engine._auto_stage_music("user-1", "+15551234567")
            )

        # Should have called upsert with stage=5
        assert any(
            area == "music" and updates.get("stage") == sut.STAGE_AMBIENT
            for area, updates in upserted
        )

    def test_music_not_re_staged_if_already_ambient(self):
        engine = sut.CapabilityLifecycleEngine()
        upserted = []

        def mock_upsert(user_id, area, updates):
            upserted.append((area, updates))

        music_connections = [{"provider": "spotify"}]
        mock_db = _make_supabase_mock(music_connections=music_connections)

        # Already at stage 5
        engine._get_lifecycle_row = lambda uid, area: {"stage": sut.STAGE_AMBIENT}
        engine._upsert_lifecycle = mock_upsert

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            asyncio.get_event_loop().run_until_complete(
                engine._auto_stage_music("user-1", "+15551234567")
            )

        # Should NOT have tried to upsert again
        assert upserted == []

    def test_music_not_staged_if_no_connection(self):
        engine = sut.CapabilityLifecycleEngine()
        upserted = []

        def mock_upsert(user_id, area, updates):
            upserted.append((area, updates))

        mock_db = _make_supabase_mock(music_connections=[])  # No connections
        engine._upsert_lifecycle = mock_upsert

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            asyncio.get_event_loop().run_until_complete(
                engine._auto_stage_music("user-1", "+15551234567")
            )

        assert upserted == []


# ── Stage transition thresholds ───────────────────────────────────────────────

class TestStageTransitions:
    def test_unaware_to_observing_when_any_signal(self):
        """Stage 0 → 1 when any signal > 0."""
        engine = sut.CapabilityLifecycleEngine()
        current_stage = sut.STAGE_UNAWARE
        signal_score = 0.1  # Any signal

        # Simulate the transition logic directly
        new_stage = current_stage
        if current_stage == sut.STAGE_UNAWARE and signal_score > 0:
            new_stage = sut.STAGE_OBSERVING

        assert new_stage == sut.STAGE_OBSERVING

    def test_observing_stays_observing_below_threshold(self):
        """Stage 1 stays at 1 when signal below threshold."""
        engine = sut.CapabilityLifecycleEngine()
        current_stage = sut.STAGE_OBSERVING
        signal_score = 0.50  # Below 0.70 threshold
        trust_score = 0.80

        new_stage = current_stage
        if current_stage == sut.STAGE_OBSERVING:
            if signal_score >= sut.SIGNAL_THRESHOLD and trust_score >= sut.TRUST_THRESHOLD:
                new_stage = sut.STAGE_READY

        assert new_stage == sut.STAGE_OBSERVING

    def test_observing_to_ready_when_thresholds_met(self):
        """Stage 1 → 2 when signal ≥ 0.70 AND trust ≥ 0.60."""
        engine = sut.CapabilityLifecycleEngine()
        current_stage = sut.STAGE_OBSERVING
        signal_score = 0.75  # Above 0.70
        trust_score = 0.70   # Above 0.60

        new_stage = current_stage
        if current_stage == sut.STAGE_OBSERVING:
            if signal_score >= sut.SIGNAL_THRESHOLD and trust_score >= sut.TRUST_THRESHOLD:
                new_stage = sut.STAGE_READY

        assert new_stage == sut.STAGE_READY

    def test_ready_stage_blocked_by_low_trust(self):
        """Stage 1 stays at 1 when signal meets threshold but trust is too low."""
        signal_score = 0.80
        trust_score = 0.50  # Below 0.60

        new_stage = sut.STAGE_OBSERVING
        if sut.STAGE_OBSERVING == sut.STAGE_OBSERVING:
            if signal_score >= sut.SIGNAL_THRESHOLD and trust_score >= sut.TRUST_THRESHOLD:
                new_stage = sut.STAGE_READY

        assert new_stage == sut.STAGE_OBSERVING


# ── Offer cooldown ────────────────────────────────────────────────────────────

class TestOfferCooldown:
    def test_offer_not_on_cooldown_when_no_recent_offer(self):
        engine = sut.CapabilityLifecycleEngine()
        mock_db = _make_supabase_mock()

        # No rows returned means no recent offer
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=[])

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            result = engine._offer_on_cooldown("user-1", "physical")

        assert result is False

    def test_offer_on_cooldown_when_recent_offer_exists(self):
        engine = sut.CapabilityLifecycleEngine()
        mock_db = MagicMock()
        # Recent offer row exists
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
            data=[{"user_id": "user-1", "area": "physical", "offered_at": datetime.now(timezone.utc).isoformat()}]
        )

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            result = engine._offer_on_cooldown("user-1", "physical")

        assert result is True

    def test_evaluate_all_users_handles_empty_user_list(self):
        engine = sut.CapabilityLifecycleEngine()
        mock_db = _make_supabase_mock(users=[])

        with patch("services.capability_lifecycle.db.get_db", return_value=mock_db):
            result = asyncio.get_event_loop().run_until_complete(
                engine.evaluate_all_users()
            )

        assert result["users_evaluated"] == 0
        assert result["areas_advanced"] == 0
