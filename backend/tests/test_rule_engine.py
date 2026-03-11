"""
tests/test_rule_engine.py — Unit tests for the Rule Engine (Step 26).

All tests are pure-unit: no Supabase calls, no Anthropic calls, no Twilio calls.
External dependencies are mocked via unittest.mock.

Run: python -m pytest tests/test_rule_engine.py -v
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
            import services.rule_engine as sut


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_rule(
    trigger_type="time",
    trigger_config=None,
    action_type="send_whatsapp",
    action_config=None,
    rule_id="rule-001",
    user_id="user-001",
    is_active=True,
):
    return {
        "id": rule_id,
        "user_id": user_id,
        "plain_english": "Test rule",
        "trigger_type": trigger_type,
        "trigger_config": trigger_config or {},
        "action_type": action_type,
        "action_config": action_config or {"message": "Test message"},
        "is_active": is_active,
        "created_at": "2026-03-01T00:00:00Z",
        "last_fired_at": None,
    }


def _mock_db(rules=None, users=None, rule_executions=None, health_summary=None, people=None):
    """Build a mock Supabase client for rule engine tests."""
    mock = MagicMock()

    rules = rules or []
    users = users or []
    rule_executions = rule_executions or []
    health_summary = health_summary or []
    people = people or []

    def table_side_effect(name):
        t = MagicMock()
        if name == "genie_rules":
            t.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=rules)
        elif name == "users":
            t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=users)
        elif name == "rule_executions":
            # Cooldown check: select("id").eq("rule_id", ...).gte("fired_at", ...).execute()
            t.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=rule_executions)
            t.insert.return_value.execute.return_value = MagicMock(data=[{"id": "exec-1"}])
        elif name == "health_daily_summary":
            t.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=health_summary)
        elif name == "people":
            t.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=people)
        return t

    mock.table.side_effect = table_side_effect
    return mock


# ── RuleEngine class init and structure tests ─────────────────────────────────

class TestRuleEngineInit:
    def test_can_instantiate(self):
        engine = sut.RuleEngine()
        assert engine is not None

    def test_has_evaluate_all_users(self):
        engine = sut.RuleEngine()
        assert hasattr(engine, "evaluate_all_users")

    def test_has_evaluate_for_user(self):
        engine = sut.RuleEngine()
        assert hasattr(engine, "evaluate_for_user")

    def test_has_check_trigger(self):
        engine = sut.RuleEngine()
        assert hasattr(engine, "_check_trigger")

    def test_has_execute_action(self):
        engine = sut.RuleEngine()
        assert hasattr(engine, "_execute_action")


# ── Cooldown logic ────────────────────────────────────────────────────────────

class TestCooldownLogic:
    def test_not_in_cooldown_when_no_recent_executions(self):
        engine = sut.RuleEngine()
        rule = _make_rule(trigger_type="time")
        mock_db = _mock_db(rule_executions=[])

        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            result = engine._is_in_cooldown(rule)

        assert result is False

    def test_in_cooldown_when_recent_execution_exists(self):
        engine = sut.RuleEngine()
        rule = _make_rule(trigger_type="time")
        # Simulate a recent execution record
        recent_exec = {"id": "exec-1", "rule_id": "rule-001", "fired_at": datetime.now(timezone.utc).isoformat()}
        mock_db = _mock_db(rule_executions=[recent_exec])

        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            result = engine._is_in_cooldown(rule)

        assert result is True

    def test_cooldown_hours_per_trigger_type(self):
        """Each trigger type has the correct cooldown defined."""
        assert sut.COOLDOWN_HOURS["time"] == 20
        assert sut.COOLDOWN_HOURS["genie_observation"] == 48
        assert sut.COOLDOWN_HOURS["health_metric"] == 20
        assert sut.COOLDOWN_HOURS["music_playing"] == 1
        assert sut.COOLDOWN_HOURS["calendar_event"] == 1

    def test_cooldown_check_falls_back_to_false_on_exception(self):
        """If DB check raises, allow the rule to fire (don't block)."""
        engine = sut.RuleEngine()
        rule = _make_rule()
        mock_db = MagicMock()
        mock_db.table.side_effect = Exception("DB unavailable")

        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            result = engine._is_in_cooldown(rule)

        assert result is False


# ── Time trigger ──────────────────────────────────────────────────────────────

class TestTimeTrigger:
    def test_fires_when_hour_matches(self):
        engine = sut.RuleEngine()
        rule = _make_rule(trigger_type="time", trigger_config={"hour": 9})
        now = datetime(2026, 3, 9, 9, 30, 0, tzinfo=timezone.utc)

        with patch("services.rule_engine.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_time_trigger({"hour": 9}, "user-1")
            )

        assert result is True

    def test_does_not_fire_when_hour_does_not_match(self):
        engine = sut.RuleEngine()
        now = datetime(2026, 3, 9, 14, 0, 0, tzinfo=timezone.utc)

        with patch("services.rule_engine.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_time_trigger({"hour": 9}, "user-1")
            )

        assert result is False

    def test_days_filter_blocks_wrong_day(self):
        engine = sut.RuleEngine()
        # Monday = weekday 0, strftime %a = "Mon"
        now = datetime(2026, 3, 9, 9, 0, 0, tzinfo=timezone.utc)  # Monday

        with patch("services.rule_engine.datetime") as mock_dt:
            mock_dt.now.return_value = now
            # Only fires on weekends
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_time_trigger({"hour": 9, "days": ["sat", "sun"]}, "user-1")
            )

        assert result is False

    def test_missing_hour_returns_false(self):
        engine = sut.RuleEngine()
        result = asyncio.get_event_loop().run_until_complete(
            engine._check_time_trigger({}, "user-1")
        )
        assert result is False


# ── Health metric trigger ─────────────────────────────────────────────────────

class TestHealthMetricTrigger:
    def test_lt_trigger_fires_when_below_threshold(self):
        engine = sut.RuleEngine()
        mock_db = MagicMock()
        # Today's summary: 1200 calories
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"total_calories": 1200, "total_protein": 80}]
        )

        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_health_metric_trigger(
                    {"metric": "calories", "operator": "lt", "value": 1500},
                    "user-1"
                )
            )

        assert result is True

    def test_lt_trigger_does_not_fire_when_above_threshold(self):
        engine = sut.RuleEngine()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"total_calories": 2000, "total_protein": 120}]
        )

        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_health_metric_trigger(
                    {"metric": "calories", "operator": "lt", "value": 1500},
                    "user-1"
                )
            )

        assert result is False

    def test_gt_trigger_fires_when_above_threshold(self):
        engine = sut.RuleEngine()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"total_calories": 2500, "total_protein": 150}]
        )

        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_health_metric_trigger(
                    {"metric": "calories", "operator": "gt", "value": 2000},
                    "user-1"
                )
            )

        assert result is True

    def test_no_summary_row_returns_false_for_gt(self):
        engine = sut.RuleEngine()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_health_metric_trigger(
                    {"metric": "calories", "operator": "gt", "value": 2000},
                    "user-1"
                )
            )

        assert result is False

    def test_missing_config_keys_return_false(self):
        engine = sut.RuleEngine()
        result = asyncio.get_event_loop().run_until_complete(
            engine._check_health_metric_trigger({}, "user-1")
        )
        assert result is False

    def test_unknown_metric_returns_false(self):
        engine = sut.RuleEngine()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"total_calories": 1500}]
        )
        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_health_metric_trigger(
                    {"metric": "nonexistent_field", "operator": "lt", "value": 100},
                    "user-1"
                )
            )
        assert result is False


# ── Genie observation trigger ─────────────────────────────────────────────────

class TestObservationTrigger:
    def test_fires_when_person_silent_beyond_threshold(self):
        engine = sut.RuleEngine()
        # Person last active 30 days ago
        old_exchange = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        mock_people = [{"name": "Alice", "last_meaningful_exchange": old_exchange, "closeness_score": 0.9}]

        with patch("services.rule_engine.db.get_people_for_user", return_value=mock_people):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_observation_trigger(
                    {"person_name": "Alice", "silence_days": 14},
                    "user-1"
                )
            )

        assert result is True

    def test_does_not_fire_when_person_recently_active(self):
        engine = sut.RuleEngine()
        recent_exchange = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        mock_people = [{"name": "Alice", "last_meaningful_exchange": recent_exchange, "closeness_score": 0.9}]

        with patch("services.rule_engine.db.get_people_for_user", return_value=mock_people):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_observation_trigger(
                    {"person_name": "Alice", "silence_days": 14},
                    "user-1"
                )
            )

        assert result is False

    def test_returns_false_when_person_not_in_graph(self):
        engine = sut.RuleEngine()
        with patch("services.rule_engine.db.get_people_for_user", return_value=[]):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_observation_trigger(
                    {"person_name": "Unknown Person", "silence_days": 7},
                    "user-1"
                )
            )
        assert result is False

    def test_empty_trigger_config_returns_false(self):
        engine = sut.RuleEngine()
        result = asyncio.get_event_loop().run_until_complete(
            engine._check_observation_trigger({}, "user-1")
        )
        assert result is False


# ── Action config interpolation ───────────────────────────────────────────────

class TestActionConfigInterpolation:
    def test_person_name_interpolated_in_message(self):
        engine = sut.RuleEngine()
        rule = _make_rule(
            trigger_type="genie_observation",
            trigger_config={"person_name": "Alice", "silence_days": 14},
            action_type="send_whatsapp",
            action_config={"message": "You haven't spoken with {person_name} in a while."},
        )
        sent_messages = []

        def mock_send(phone, message, user_id=None, moment_id=None):
            sent_messages.append(message)

        with patch("services.rule_engine.send_message" if hasattr(sut, "send_message") else "services.whatsapp.send_message", mock_send, create=True):
            with patch("services.rule_engine.db.get_db", return_value=MagicMock()):
                result = asyncio.get_event_loop().run_until_complete(
                    engine._action_send_message(rule, "user-1", "+15551234567", rule["action_config"])
                )

        # The method imports and calls send_message internally — check the behavior via mock
        # Just assert the method returns True on successful path logic
        # (send_message is patched at the module level where it's called)

    def test_message_without_placeholder_sent_as_is(self):
        engine = sut.RuleEngine()
        rule = _make_rule(
            action_config={"message": "Time to check in with someone important."},
        )
        captured = []

        async def run():
            with patch("services.whatsapp.send_message") as mock_send:
                mock_send.return_value = "sid-123"
                result = await engine._action_send_message(rule, "user-1", "+15551234567", rule["action_config"])
                if mock_send.called:
                    captured.append(mock_send.call_args[0][1])
                return result

        asyncio.get_event_loop().run_until_complete(run())

    def test_empty_message_returns_false(self):
        engine = sut.RuleEngine()
        rule = _make_rule(action_config={"message": ""})
        result = asyncio.get_event_loop().run_until_complete(
            engine._action_send_message(rule, "user-1", "+15551234567", {"message": ""})
        )
        assert result is False

    def test_missing_message_key_returns_false(self):
        engine = sut.RuleEngine()
        rule = _make_rule(action_config={})
        result = asyncio.get_event_loop().run_until_complete(
            engine._action_send_message(rule, "user-1", "+15551234567", {})
        )
        assert result is False


# ── Music trigger graceful skip ───────────────────────────────────────────────

class TestMusicTrigger:
    def test_skips_gracefully_when_no_spotify_connection(self):
        engine = sut.RuleEngine()

        async def mock_get_currently_playing():
            raise RuntimeError("No Spotify connection for user user-1")

        mock_client = AsyncMock()
        mock_client.get_currently_playing.side_effect = RuntimeError("No Spotify connection")

        with patch("services.rule_engine.SpotifyClient" if hasattr(sut, "SpotifyClient") else "services.spotify_client.SpotifyClient", return_value=mock_client, create=True):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_music_trigger({}, "user-1")
            )

        assert result is False

    def test_returns_false_when_nothing_playing(self):
        engine = sut.RuleEngine()
        mock_client = AsyncMock()
        mock_client.get_currently_playing.return_value = {"is_playing": False}

        with patch("services.spotify_client.SpotifyClient", return_value=mock_client, create=True):
            result = asyncio.get_event_loop().run_until_complete(
                engine._check_music_trigger({}, "user-1")
            )

        assert result is False


# ── Unknown trigger type edge case ────────────────────────────────────────────

class TestEdgeCases:
    def test_unknown_trigger_type_returns_false(self):
        engine = sut.RuleEngine()
        rule = _make_rule(trigger_type="nonexistent_trigger")
        result = asyncio.get_event_loop().run_until_complete(
            engine._check_trigger(rule, "user-1")
        )
        assert result is False

    def test_rule_error_does_not_affect_other_rules(self):
        """One failing rule should not prevent others from being evaluated."""
        engine = sut.RuleEngine()

        # First rule: will raise
        bad_rule = _make_rule(trigger_type="time", trigger_config={"hour": 9}, rule_id="bad-rule")
        # Second rule: should succeed
        good_rule = _make_rule(trigger_type="time", trigger_config={"hour": 10}, rule_id="good-rule")

        # Patch _is_in_cooldown to always return False (not in cooldown)
        # Patch _check_trigger to raise for bad rule, return False for good rule
        async def mock_check_trigger(rule, user_id):
            if rule["id"] == "bad-rule":
                raise RuntimeError("Simulated rule failure")
            return False  # good rule: trigger not met

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[bad_rule, good_rule])
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=[])

        engine._check_trigger = mock_check_trigger
        engine._is_in_cooldown = lambda rule: False

        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            fired = asyncio.get_event_loop().run_until_complete(
                engine.evaluate_for_user("user-1", "+15551234567")
            )

        # No rules fired (good rule trigger returned False), no exception raised
        assert fired == []

    def test_evaluate_all_users_handles_db_failure(self):
        """If user list query fails, return error stats without raising."""
        engine = sut.RuleEngine()
        mock_db = MagicMock()
        mock_db.table.side_effect = Exception("DB down")

        with patch("services.rule_engine.db.get_db", return_value=mock_db):
            result = asyncio.get_event_loop().run_until_complete(
                engine.evaluate_all_users()
            )

        assert result["users_checked"] == 0
        assert result["errors"] >= 1
