"""
tests/test_habit.py — Unit tests for services/habit.py (Sprint 3)

Covers:
- _parse_answer()             — numeric extraction, goal_type normalization
- _answer_ack()               — correct acknowledgment per field
- get_next_question()         — state machine: all 6 states + edge cases
- mark_question_asked()       — pending state written to DB
- handle_question_answer()    — answer stored, counter advanced, ack returned
- is_awaiting_answer()        — reflects pending_question_idx
- pick_nudge_variant()        — never repeats, handles edge cases
- question_was_sent_today()   — date comparison
- get_weekly_summary()        — aggregation from health_daily_summary
- build_weekly_rollup_message() — message construction + suppression
"""
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

from services.habit import (
    LEARNING_QUESTIONS,
    get_health_profile,
    get_next_question,
    mark_question_asked,
    handle_question_answer,
    is_awaiting_answer,
    ensure_health_profile_exists,
    pick_nudge_variant,
    question_was_sent_today,
    get_last_nudge_variant_idx,
    record_nudge_variant,
    get_weekly_summary,
    build_weekly_rollup_message,
    _parse_answer,
    _answer_ack,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile(
    questions_completed=0,
    pending_question_idx=None,
    last_question_date=None,
    last_nudge_variant_idx=-1,
    **kwargs,
):
    return {
        "id": "prof-1",
        "user_id": "user-1",
        "questions_completed": questions_completed,
        "pending_question_idx": pending_question_idx,
        "last_question_date": last_question_date,
        "last_nudge_variant_idx": last_nudge_variant_idx,
        **kwargs,
    }


def _mock_db_with_profile(profile_data):
    """Return a db mock whose health_profile table returns profile_data."""
    mock_db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value.data = [profile_data] if profile_data else []
    mock_db.table.return_value.select.return_value.eq.return_value.limit.return_value = chain
    # For upsert operations
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{}]
    return mock_db


# ─────────────────────────────────────────────────────────────────────────────
# _parse_answer
# ─────────────────────────────────────────────────────────────────────────────

class TestParseAnswer:
    def test_calorie_goal_extracts_integer(self):
        assert _parse_answer("calorie_goal", "around 2000 calories") == "2000"

    def test_calorie_goal_no_number_returns_raw(self):
        result = _parse_answer("calorie_goal", "not sure really")
        assert result == "not sure really"

    def test_protein_goal_extracts_number(self):
        assert _parse_answer("protein_goal_g", "I aim for 160g") == "160"

    def test_training_days_extracts_number(self):
        assert _parse_answer("training_days_per_week", "4 days a week") == "4"

    def test_goal_type_lose(self):
        assert _parse_answer("goal_type", "trying to lose weight") == "lose"

    def test_goal_type_gain(self):
        assert _parse_answer("goal_type", "building muscle right now") == "gain"

    def test_goal_type_maintain(self):
        assert _parse_answer("goal_type", "just staying consistent") == "maintain"

    def test_goal_type_cut_synonym(self):
        assert _parse_answer("goal_type", "I'm in a cut") == "lose"

    def test_goal_type_unknown_returns_raw(self):
        result = _parse_answer("goal_type", "it's complicated")
        assert result == "it's complicated"

    def test_food_restrictions_stored_verbatim(self):
        assert _parse_answer("food_restrictions", "No gluten, dairy free") == "No gluten, dairy free"

    def test_biggest_struggle_capped_at_200(self):
        long = "x" * 300
        assert len(_parse_answer("biggest_struggle", long)) == 200

    def test_food_restrictions_capped_at_200(self):
        long = "y" * 300
        assert len(_parse_answer("food_restrictions", long)) == 200


# ─────────────────────────────────────────────────────────────────────────────
# _answer_ack
# ─────────────────────────────────────────────────────────────────────────────

class TestAnswerAck:
    def test_calorie_ack_includes_value(self):
        ack = _answer_ack("calorie_goal", "2000", 1)
        assert "2000" in ack

    def test_protein_ack_includes_value(self):
        ack = _answer_ack("protein_goal_g", "160", 2)
        assert "160" in ack

    def test_goal_type_lose_ack(self):
        ack = _answer_ack("goal_type", "lose", 4)
        assert "deficit" in ack.lower()

    def test_goal_type_gain_ack(self):
        ack = _answer_ack("goal_type", "gain", 4)
        assert "building" in ack.lower() or "got it" in ack.lower()

    def test_goal_type_maintain_ack(self):
        ack = _answer_ack("goal_type", "maintain", 4)
        assert "consistent" in ack.lower()

    def test_last_question_adds_completion_note(self):
        total = len(LEARNING_QUESTIONS)
        ack = _answer_ack("biggest_struggle", "portion control", total)
        assert "that's everything" in ack.lower() or "good picture" in ack.lower()

    def test_not_last_question_no_completion_note(self):
        ack = _answer_ack("calorie_goal", "2000", 1)
        assert "that's everything" not in ack.lower()


# ─────────────────────────────────────────────────────────────────────────────
# get_next_question
# ─────────────────────────────────────────────────────────────────────────────

class TestGetNextQuestion:
    @patch("services.habit.db")
    def test_returns_none_when_no_profile(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(None)
        assert get_next_question("user-1") is None

    @patch("services.habit.db")
    def test_returns_first_question_on_fresh_profile(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(_profile())
        result = get_next_question("user-1")
        assert result is not None
        idx, text = result
        assert idx == 0
        assert "calorie" in text.lower()

    @patch("services.habit.db")
    def test_returns_none_when_all_complete(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(
            _profile(questions_completed=len(LEARNING_QUESTIONS))
        )
        assert get_next_question("user-1") is None

    @patch("services.habit.db")
    def test_returns_none_when_pending_answer(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(
            _profile(pending_question_idx=0)
        )
        assert get_next_question("user-1") is None

    @patch("services.habit.db")
    def test_returns_none_when_asked_today(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(
            _profile(last_question_date=date.today().isoformat())
        )
        assert get_next_question("user-1") is None

    @patch("services.habit.db")
    def test_returns_question_when_asked_yesterday(self, mock_db_module):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        mock_db_module.get_db.return_value = _mock_db_with_profile(
            _profile(questions_completed=2, last_question_date=yesterday)
        )
        result = get_next_question("user-1")
        assert result is not None
        assert result[0] == 2  # Third question (index 2)

    @patch("services.habit.db")
    def test_correct_question_index_returned(self, mock_db_module):
        for i in range(len(LEARNING_QUESTIONS)):
            mock_db_module.get_db.return_value = _mock_db_with_profile(
                _profile(questions_completed=i)
            )
            result = get_next_question("user-1")
            assert result[0] == i


# ─────────────────────────────────────────────────────────────────────────────
# mark_question_asked
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkQuestionAsked:
    @patch("services.habit.db")
    def test_sets_pending_idx_and_date(self, mock_db_module):
        mock_db = MagicMock()
        mock_db_module.get_db.return_value = mock_db

        # Simulate existing profile row
        existing_chain = MagicMock()
        existing_chain.execute.return_value.data = [{"id": "prof-1"}]
        mock_db.table.return_value.select.return_value.eq.return_value.limit.return_value = existing_chain
        mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]

        mark_question_asked("user-1", 2)

        update_call = mock_db.table.return_value.update.call_args[0][0]
        assert update_call["pending_question_idx"] == 2
        assert update_call["last_question_date"] == date.today().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# handle_question_answer
# ─────────────────────────────────────────────────────────────────────────────

class TestHandleQuestionAnswer:
    @patch("services.habit.db")
    def test_returns_none_when_no_profile(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(None)
        assert handle_question_answer("user-1", "2000") is None

    @patch("services.habit.db")
    def test_returns_none_when_no_pending(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(_profile())
        assert handle_question_answer("user-1", "2000") is None

    @patch("services.habit.db")
    def test_stores_answer_and_advances_counter(self, mock_db_module):
        mock_db = MagicMock()
        mock_db_module.get_db.return_value = mock_db

        # get_health_profile returns profile with pending idx 0
        profile_chain = MagicMock()
        profile_chain.execute.return_value.data = [_profile(pending_question_idx=0)]
        # existing check for upsert
        existing_chain = MagicMock()
        existing_chain.execute.return_value.data = [{"id": "prof-1"}]

        call_count = [0]
        def table_select_side_effect(*args):
            m = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: get_health_profile
                m.eq.return_value.limit.return_value = profile_chain
            else:
                # Second call: existing check in _upsert
                m.eq.return_value.limit.return_value = existing_chain
            return m

        mock_db.table.return_value.select.side_effect = table_select_side_effect
        mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]

        result = handle_question_answer("user-1", "2000 calories per day")

        assert result is not None
        assert "2000" in result

        # Check what was upserted
        update_payload = mock_db.table.return_value.update.call_args[0][0]
        assert update_payload["calorie_goal"] == "2000"
        assert update_payload["questions_completed"] == 1
        assert update_payload["pending_question_idx"] is None

    @patch("services.habit.db")
    def test_final_question_completion_message(self, mock_db_module):
        """After question 6 (idx 5), ack includes completion note."""
        mock_db = MagicMock()
        mock_db_module.get_db.return_value = mock_db

        last_idx = len(LEARNING_QUESTIONS) - 1
        profile_chain = MagicMock()
        profile_chain.execute.return_value.data = [_profile(pending_question_idx=last_idx)]
        existing_chain = MagicMock()
        existing_chain.execute.return_value.data = [{"id": "prof-1"}]

        call_count = [0]
        def table_select_side_effect(*args):
            m = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                m.eq.return_value.limit.return_value = profile_chain
            else:
                m.eq.return_value.limit.return_value = existing_chain
            return m

        mock_db.table.return_value.select.side_effect = table_select_side_effect
        mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]

        result = handle_question_answer("user-1", "portion control")
        assert result is not None
        assert "everything" in result.lower() or "picture" in result.lower()


# ─────────────────────────────────────────────────────────────────────────────
# is_awaiting_answer
# ─────────────────────────────────────────────────────────────────────────────

class TestIsAwaitingAnswer:
    @patch("services.habit.db")
    def test_false_when_no_profile(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(None)
        assert is_awaiting_answer("user-1") is False

    @patch("services.habit.db")
    def test_false_when_no_pending(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(_profile())
        assert is_awaiting_answer("user-1") is False

    @patch("services.habit.db")
    def test_true_when_pending_set(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(
            _profile(pending_question_idx=2)
        )
        assert is_awaiting_answer("user-1") is True


# ─────────────────────────────────────────────────────────────────────────────
# pick_nudge_variant
# ─────────────────────────────────────────────────────────────────────────────

class TestPickNudgeVariant:
    VARIANTS = ["A", "B", "C", "D"]

    def test_never_returns_same_as_last(self):
        for last in range(len(self.VARIANTS)):
            for _ in range(20):  # Run many times to catch random failures
                idx, text = pick_nudge_variant(self.VARIANTS, last)
                assert idx != last

    def test_returns_valid_text(self):
        idx, text = pick_nudge_variant(self.VARIANTS, -1)
        assert text in self.VARIANTS

    def test_single_variant_returns_it(self):
        idx, text = pick_nudge_variant(["Only one"], 0)
        assert text == "Only one"

    def test_works_with_last_minus_one(self):
        """last_idx of -1 means never used — all variants are available."""
        results = set()
        for _ in range(50):
            idx, _ = pick_nudge_variant(self.VARIANTS, -1)
            results.add(idx)
        assert len(results) > 1  # Should cycle through multiple variants


# ─────────────────────────────────────────────────────────────────────────────
# question_was_sent_today
# ─────────────────────────────────────────────────────────────────────────────

class TestQuestionWasSentToday:
    @patch("services.habit.db")
    def test_false_when_no_profile(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(None)
        assert question_was_sent_today("user-1") is False

    @patch("services.habit.db")
    def test_false_when_date_is_yesterday(self, mock_db_module):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        mock_db_module.get_db.return_value = _mock_db_with_profile(
            _profile(last_question_date=yesterday)
        )
        assert question_was_sent_today("user-1") is False

    @patch("services.habit.db")
    def test_true_when_date_is_today(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(
            _profile(last_question_date=date.today().isoformat())
        )
        assert question_was_sent_today("user-1") is True

    @patch("services.habit.db")
    def test_false_when_no_date_set(self, mock_db_module):
        mock_db_module.get_db.return_value = _mock_db_with_profile(_profile())
        assert question_was_sent_today("user-1") is False


# ─────────────────────────────────────────────────────────────────────────────
# get_weekly_summary
# ─────────────────────────────────────────────────────────────────────────────

class TestGetWeeklySummary:
    def _mock_summary_rows(self, rows):
        mock_db = MagicMock()
        chain = MagicMock()
        chain.execute.return_value.data = rows
        mock_db.table.return_value.select.return_value \
            .eq.return_value.gte.return_value = chain
        return mock_db

    @patch("services.habit.db")
    def test_empty_returns_zeros(self, mock_db_module):
        mock_db_module.get_db.return_value = self._mock_summary_rows([])
        result = get_weekly_summary("user-1")
        assert result["days_logged"] == 0
        assert result["avg_calories"] == 0

    @patch("services.habit.db")
    def test_counts_only_days_with_food(self, mock_db_module):
        rows = [
            {"total_calories": 2000, "total_protein": 150, "trained": False, "summary_date": "2026-03-01"},
            {"total_calories": 0, "total_protein": 0, "trained": True, "summary_date": "2026-03-02"},
            {"total_calories": 1800, "total_protein": 130, "trained": True, "summary_date": "2026-03-03"},
        ]
        mock_db_module.get_db.return_value = self._mock_summary_rows(rows)
        result = get_weekly_summary("user-1")
        assert result["days_logged"] == 2  # 0-calorie day excluded
        assert result["training_sessions"] == 2  # Both trained days counted

    @patch("services.habit.db")
    def test_avg_calories_correct(self, mock_db_module):
        rows = [
            {"total_calories": 2000, "total_protein": 150, "trained": False, "summary_date": "2026-03-01"},
            {"total_calories": 2200, "total_protein": 160, "trained": False, "summary_date": "2026-03-02"},
        ]
        mock_db_module.get_db.return_value = self._mock_summary_rows(rows)
        result = get_weekly_summary("user-1")
        assert result["avg_calories"] == 2100.0
        assert result["avg_protein_g"] == 155.0

    @patch("services.habit.db")
    def test_db_error_returns_zero_dict(self, mock_db_module):
        mock_db_module.get_db.side_effect = RuntimeError("DB down")
        result = get_weekly_summary("user-1")
        assert result["days_logged"] == 0
        assert result["avg_calories"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# build_weekly_rollup_message
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildWeeklyRollupMessage:
    def _summary(self, days=5, avg_cal=2000, avg_prot=150, sessions=3):
        return {
            "days_logged": days,
            "avg_calories": avg_cal,
            "avg_protein_g": avg_prot,
            "training_sessions": sessions,
        }

    def test_returns_none_when_fewer_than_2_days(self):
        assert build_weekly_rollup_message(self._summary(days=0)) is None
        assert build_weekly_rollup_message(self._summary(days=1)) is None

    def test_returns_string_with_2_or_more_days(self):
        result = build_weekly_rollup_message(self._summary(days=2))
        assert result is not None
        assert isinstance(result, str)

    def test_includes_days_in_message(self):
        result = build_weekly_rollup_message(self._summary(days=5))
        assert "5" in result

    def test_includes_avg_calories(self):
        result = build_weekly_rollup_message(self._summary(avg_cal=1950))
        assert "1950" in result

    def test_includes_avg_protein(self):
        result = build_weekly_rollup_message(self._summary(avg_prot=142.5))
        assert "142.5" in result

    def test_includes_session_count(self):
        result = build_weekly_rollup_message(self._summary(sessions=4))
        assert "4" in result
        assert "session" in result.lower()

    def test_plural_sessions(self):
        result = build_weekly_rollup_message(self._summary(sessions=3))
        assert "sessions" in result

    def test_singular_session(self):
        result = build_weekly_rollup_message(self._summary(sessions=1))
        assert "session" in result and "sessions" not in result

    def test_no_training_note_when_days_gte_3(self):
        result = build_weekly_rollup_message(self._summary(days=4, sessions=0))
        assert "no training" in result.lower()

    def test_no_training_note_absent_when_days_lt_3(self):
        result = build_weekly_rollup_message(self._summary(days=2, sessions=0))
        assert "no training" not in result.lower()
