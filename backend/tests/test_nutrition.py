"""
tests/test_nutrition.py — Unit tests for the NutritionService (Sprint 1).

All tests are pure-unit: no Supabase calls, no Anthropic calls.
External dependencies are mocked via unittest.mock.

Run: python -m pytest tests/test_nutrition.py -v
"""
import json
from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the module under test.
# Patch settings before the module loads to avoid needing a real .env file.
# ---------------------------------------------------------------------------
_MOCK_SETTINGS = MagicMock()
_MOCK_SETTINGS.claude_model = "claude-sonnet-4-5"
_MOCK_SETTINGS.anthropic_api_key = "test-key"
_MOCK_SETTINGS.openai_api_key = "test-key"

with patch("config.get_settings", return_value=_MOCK_SETTINGS):
    import services.nutrition as sut  # system under test


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _parsed(
    calories: float = 400,
    protein: float = 25,
    carbs: float = 40,
    fat: float = 12,
    confidence: float = 0.9,
    clarification_question: str = None,
    foods: list = None,
) -> dict:
    """Build a minimal parsed food dict for testing."""
    return {
        "foods": foods if foods is not None else [{"name": "test food", "quantity": 1, "unit": "serving",
                             "calories": calories, "protein_g": protein,
                             "carbs_g": carbs, "fat_g": fat, "confidence": confidence}],
        "total_calories": calories,
        "total_protein": protein,
        "total_carbs": carbs,
        "total_fat": fat,
        "overall_confidence": confidence,
        "clarification_question": clarification_question,
        "meal_type_hint": None,
        "parsing_notes": "test",
    }


def _daily(
    calories: float = 0,
    protein: float = 0,
    calorie_goal: float = 2000,
    protein_goal: float = 150,
    nudge_sent: bool = False,
) -> dict:
    return {
        "total_calories": calories,
        "total_protein": protein,
        "calorie_goal": calorie_goal,
        "protein_goal": protein_goal,
        "nudge_sent": nudge_sent,
    }


# ── is_food_intent ────────────────────────────────────────────────────────────

class TestIsFoodIntent:
    def test_simple_had(self):
        assert sut.is_food_intent("just had eggs and toast") is True

    def test_meal_context(self):
        assert sut.is_food_intent("lunch was a chipotle burrito bowl") is True

    def test_drink(self):
        assert sut.is_food_intent("drank a coffee this morning") is True

    def test_restaurant(self):
        assert sut.is_food_intent("grabbed a sandwich from the deli") is True

    def test_explicit_calories(self):
        assert sut.is_food_intent("had 500 cal of oatmeal") is True

    def test_protein_mention(self):
        assert sut.is_food_intent("protein shake after the gym") is True

    def test_snack(self):
        assert sut.is_food_intent("some chips and salsa for snack") is True

    def test_non_food_message(self):
        assert sut.is_food_intent("how's Lauren doing?") is False

    def test_relationship_message(self):
        assert sut.is_food_intent("tell me something about Barry") is False

    def test_session_trigger_not_food(self):
        # Session triggers must never be misclassified as food
        assert sut.is_food_intent("starting session") is False

    def test_starting_gym_session(self):
        assert sut.is_food_intent("start session") is False

    def test_empty_string(self):
        assert sut.is_food_intent("") is False

    def test_question_about_food(self):
        # "for lunch" is in signals — this is a known acceptable false positive.
        # The router handles it gracefully: parse returns 0 cal, ack=None, falls
        # through to the conversation agent. No data is stored for 0-calorie parses.
        # Verified acceptable in design review 2026-03-09.
        assert sut.is_food_intent("what should I eat for lunch?") is True


# ── is_session_trigger ────────────────────────────────────────────────────────

class TestIsSessionTrigger:
    def test_starting_session(self):
        assert sut.is_session_trigger("starting session") is True

    def test_start_session(self):
        assert sut.is_session_trigger("start session now") is True

    def test_session_start(self):
        assert sut.is_session_trigger("session start") is True

    def test_gym_session(self):
        assert sut.is_session_trigger("gym session starting") is True

    def test_non_session(self):
        assert sut.is_session_trigger("just had lunch") is False

    def test_unrelated(self):
        assert sut.is_session_trigger("how's it going?") is False


# ── _effective_date ───────────────────────────────────────────────────────────

class TestEffectiveDate:
    def test_normal_hour_returns_today(self):
        """After 3am local → current date."""
        # Patch datetime.now to return 8am UTC
        fixed = datetime(2026, 3, 9, 8, 0, 0, tzinfo=timezone.utc)
        with patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            result = sut._effective_date(user_tz_offset=0)
        assert result == date(2026, 3, 9)

    def test_before_3am_returns_previous_day(self):
        """Before 3am local → previous date (midnight rule)."""
        fixed = datetime(2026, 3, 9, 2, 0, 0, tzinfo=timezone.utc)  # 2am UTC = 2am local
        with patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            result = sut._effective_date(user_tz_offset=0)
        assert result == date(2026, 3, 8)

    def test_tz_offset_applied(self):
        """SF at UTC 6am (offset -8) = 10pm local previous day → previous date."""
        fixed = datetime(2026, 3, 9, 6, 0, 0, tzinfo=timezone.utc)   # 6am UTC = 10pm PT prev day
        with patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            result = sut._effective_date(user_tz_offset=-8)
        assert result == date(2026, 3, 8)

    def test_exactly_3am_is_current_day(self):
        """At exactly 3am → current day (boundary is strictly < 3)."""
        fixed = datetime(2026, 3, 9, 3, 0, 0, tzinfo=timezone.utc)
        with patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            result = sut._effective_date(user_tz_offset=0)
        assert result == date(2026, 3, 9)


# ── _infer_meal_type ──────────────────────────────────────────────────────────

class TestInferMealType:
    @pytest.mark.parametrize("hour,expected", [
        (6, "breakfast"),
        (9, "breakfast"),
        (11, "lunch"),
        (13, "lunch"),
        (15, "snack"),
        (16, "snack"),
        (18, "dinner"),
        (20, "dinner"),
        (23, "snack"),
        (1,  "snack"),
    ])
    def test_meal_type_by_hour(self, hour, expected):
        fixed = datetime(2026, 3, 9, hour, 0, 0, tzinfo=timezone.utc)
        with patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            result = sut._infer_meal_type(user_tz_offset=0)
        assert result == expected


# ── _significance_score ───────────────────────────────────────────────────────

class TestSignificanceScore:
    def test_low_calorie_entry_low_significance(self):
        p = _parsed(calories=200, protein=10)
        d = _daily(calories=500, protein=50, calorie_goal=2000, protein_goal=150)
        assert sut._significance_score(p, d) < sut.SIGNIFICANCE_THRESHOLD

    def test_over_calorie_goal_high_significance(self):
        p = _parsed(calories=200)
        d = _daily(calories=2600, calorie_goal=2000)   # 30% over goal
        score = sut._significance_score(p, d)
        assert score >= sut.SIGNIFICANCE_THRESHOLD

    def test_large_single_entry_raises_score(self):
        p = _parsed(calories=700)
        d = _daily(calories=700, calorie_goal=2000)
        score = sut._significance_score(p, d)
        assert score > 0.0

    def test_low_protein_at_night_raises_score(self):
        p = _parsed(calories=200, protein=5)
        d = _daily(calories=1500, protein=50, protein_goal=150)
        fixed = datetime(2026, 3, 9, 21, 0, 0, tzinfo=timezone.utc)  # 9pm
        with patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            score = sut._significance_score(p, d)
        assert score >= sut.SIGNIFICANCE_THRESHOLD


# ── build_acknowledgment ──────────────────────────────────────────────────────

class TestBuildAcknowledgment:
    def test_week_one_always_acks(self):
        """During the first 7 days, always returns an acknowledgment."""
        p = _parsed(calories=380, protein=22)
        d = _daily(calories=380, protein=22)
        result = sut.build_acknowledgment(p, d, days_logging=3)
        assert result is not None
        assert "380" in result
        assert "22" in result

    def test_week_one_first_entry_of_day(self):
        """First entry of day — shows just the entry, no 'at X for today'."""
        p = _parsed(calories=380, protein=22)
        d = _daily(calories=0)  # nothing else logged yet
        result = sut.build_acknowledgment(p, d, days_logging=2)
        assert result is not None

    def test_after_week_one_low_significance_silent(self):
        """After habit established, low-significance entries return None."""
        p = _parsed(calories=200, protein=10)
        d = _daily(calories=800, protein=80, calorie_goal=2000, protein_goal=150)
        result = sut.build_acknowledgment(p, d, days_logging=10)
        assert result is None

    def test_after_week_one_over_goal_surfaces(self):
        """Over calorie goal → surfaces after habit week."""
        p = _parsed(calories=200)
        d = _daily(calories=2700, calorie_goal=2000)
        result = sut.build_acknowledgment(p, d, days_logging=10)
        assert result is not None
        assert "over" in result.lower() or "2700" in result

    def test_clarification_question_returned_when_parse_empty(self):
        """If Claude couldn't parse foods but has a question, return the question."""
        p = _parsed(calories=0, protein=0, confidence=0.4,
                    foods=[], clarification_question="Just coffee or with milk?")
        d = _daily()
        result = sut.build_acknowledgment(p, d, days_logging=5)
        assert result == "Just coffee or with milk?"

    def test_ack_contains_calories_and_protein(self):
        """Week 1 ack always includes both calories and protein."""
        p = _parsed(calories=750, protein=40)
        d = _daily(calories=750, protein=40)
        result = sut.build_acknowledgment(p, d, days_logging=1)
        assert "750" in result
        assert "40" in result


# ── parse_food_input (mocked Claude) ─────────────────────────────────────────

class TestParseFoodInput:
    def _mock_claude_response(self, payload: dict):
        """Set up _anthropic mock to return a given JSON payload."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(payload))]
        return mock_response

    def test_simple_food_parsed(self):
        payload = _parsed(calories=380, protein=22)
        with patch.object(sut._anthropic.messages, "create", return_value=self._mock_claude_response(payload)):
            result = sut.parse_food_input("just had eggs and toast")
        assert result["total_calories"] == 380
        assert result["total_protein"] == 22
        assert result["overall_confidence"] == 0.9

    def test_restaurant_realistic_calories(self):
        """Chipotle burrito bowl should come back with ≥700 calories."""
        payload = _parsed(calories=820, protein=45)
        with patch.object(sut._anthropic.messages, "create", return_value=self._mock_claude_response(payload)):
            result = sut.parse_food_input("chipotle burrito bowl")
        assert result["total_calories"] >= 700

    def test_vague_input_low_confidence_has_question(self):
        """Vague input → confidence < 0.6 and clarification_question not None."""
        payload = _parsed(calories=50, protein=0, confidence=0.4,
                          clarification_question="Just black coffee or with milk/sugar?")
        with patch.object(sut._anthropic.messages, "create", return_value=self._mock_claude_response(payload)):
            result = sut.parse_food_input("coffee")
        assert result["overall_confidence"] < 0.6
        assert result["clarification_question"] is not None

    def test_multiple_items_parsed(self):
        """'Eggs, toast, and coffee' → multiple food items."""
        payload = {**_parsed(calories=420, protein=24), "foods": [
            {"name": "eggs", "quantity": 2, "unit": "large", "calories": 140, "protein_g": 12, "carbs_g": 1, "fat_g": 10, "confidence": 0.95},
            {"name": "toast", "quantity": 2, "unit": "slices", "calories": 200, "protein_g": 8, "carbs_g": 36, "fat_g": 2, "confidence": 0.9},
            {"name": "coffee", "quantity": 1, "unit": "cup", "calories": 80, "protein_g": 4, "carbs_g": 8, "fat_g": 4, "confidence": 0.7},
        ]}
        with patch.object(sut._anthropic.messages, "create", return_value=self._mock_claude_response(payload)):
            result = sut.parse_food_input("eggs, toast, and a coffee with milk")
        assert len(result["foods"]) == 3

    def test_parse_failure_returns_safe_fallback(self):
        """If Claude raises, return a safe fallback with clarification question."""
        with patch.object(sut._anthropic.messages, "create", side_effect=Exception("API down")):
            result = sut.parse_food_input("something weird")
        assert result["total_calories"] == 0
        assert result["overall_confidence"] == 0.0
        assert result["clarification_question"] is not None

    def test_strips_markdown_code_fences(self):
        """Claude sometimes wraps JSON in code fences — must strip them."""
        payload = _parsed(calories=300, protein=15)
        raw_with_fences = "```json\n" + json.dumps(payload) + "\n```"
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=raw_with_fences)]
        with patch.object(sut._anthropic.messages, "create", return_value=mock_response):
            result = sut.parse_food_input("salad")
        assert result["total_calories"] == 300


# ── store_food_log (mocked Supabase) ─────────────────────────────────────────

class TestStoreFoodLog:
    def _make_supabase_mock(self, existing_row=None):
        """
        Build a Supabase mock that differentiates between table names.
        Uses side_effect on .table() so nutrition_log and health_daily_summary
        return separate mock objects and their call counts don't bleed into each other.
        """
        # Separate mock for each table
        nutrition_log_mock = MagicMock()
        nutrition_log_mock.insert.return_value.execute.return_value = MagicMock(data=[{"id": "log-1"}])

        health_summary_mock = MagicMock()

        # health_daily_summary.select().eq().eq().execute()
        select_result = MagicMock(data=[existing_row] if existing_row else [])
        health_summary_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value = select_result

        # health_daily_summary.update().eq().eq().execute()
        if existing_row:
            updated_row = {**existing_row,
                           "total_calories": existing_row["total_calories"] + 380,
                           "total_protein": existing_row["total_protein"] + 22}
            health_summary_mock.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[updated_row])

        # health_daily_summary.insert().execute()
        health_summary_mock.insert.return_value.execute.return_value = MagicMock(data=[{
            "user_id": "u1", "summary_date": "2026-03-09",
            "total_calories": 380, "total_protein": 22,
        }])

        mock_db = MagicMock()
        mock_db.table.side_effect = lambda name: {
            "nutrition_log": nutrition_log_mock,
            "health_daily_summary": health_summary_mock,
        }.get(name, MagicMock())

        # Expose named mocks for assertions
        mock_db._nutrition_log = nutrition_log_mock
        mock_db._health_summary = health_summary_mock

        return mock_db

    def test_creates_new_daily_summary_when_none_exists(self):
        mock_db = self._make_supabase_mock(existing_row=None)
        parsed = _parsed(calories=380, protein=22)
        fixed = datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc)

        with patch("services.nutrition.db.get_db", return_value=mock_db), \
             patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            sut.store_food_log("u1", "eggs and toast", parsed)

        mock_db._nutrition_log.insert.assert_called_once()
        mock_db._health_summary.insert.assert_called_once()

    def test_increments_existing_daily_summary(self):
        existing = {
            "id": "sum-1", "user_id": "u1", "summary_date": "2026-03-09",
            "total_calories": 500, "total_protein": 30,
            "calorie_goal": 2000, "protein_goal": 150, "nudge_sent": False,
        }
        mock_db = self._make_supabase_mock(existing_row=existing)
        parsed = _parsed(calories=380, protein=22)
        fixed = datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc)

        with patch("services.nutrition.db.get_db", return_value=mock_db), \
             patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            sut.store_food_log("u1", "eggs and toast", parsed)

        # Should update, not insert
        mock_db._health_summary.update.assert_called_once()
        mock_db._health_summary.insert.assert_not_called()

    def test_midnight_rule_assigns_to_previous_date(self):
        """A log at 2am UTC must be stored with yesterday's date."""
        mock_db = self._make_supabase_mock(existing_row=None)
        parsed = _parsed(calories=100, protein=5)
        # 2am UTC = yesterday for a tz_offset=0 user
        fixed = datetime(2026, 3, 9, 2, 0, 0, tzinfo=timezone.utc)

        captured_payload = {}

        def capture_insert(payload):
            captured_payload.update(payload)
            m = MagicMock()
            m.execute.return_value = MagicMock(data=[payload])
            return m

        mock_db._health_summary.insert.side_effect = capture_insert

        with patch("services.nutrition.db.get_db", return_value=mock_db), \
             patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            sut.store_food_log("u1", "late night snack", parsed, user_tz_offset=0)

        assert captured_payload.get("summary_date") == "2026-03-08"

    def test_duplicate_log_increments_not_replaces(self):
        """Second log of the day adds to totals, not overwrites them."""
        existing = {
            "id": "sum-1", "user_id": "u1", "summary_date": "2026-03-09",
            "total_calories": 750, "total_protein": 40, "nudge_sent": False,
        }
        mock_db = self._make_supabase_mock(existing_row=existing)
        parsed = _parsed(calories=380, protein=22)
        fixed = datetime(2026, 3, 9, 13, 0, 0, tzinfo=timezone.utc)

        with patch("services.nutrition.db.get_db", return_value=mock_db), \
             patch("services.nutrition.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            sut.store_food_log("u1", "second meal", parsed)

        # Must call update with incremented values
        update_call = mock_db._health_summary.update.call_args
        assert update_call is not None
        payload = update_call[0][0]
        assert payload["total_calories"] == pytest.approx(750 + 380)
        assert payload["total_protein"] == pytest.approx(40 + 22)
