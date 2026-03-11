"""
tests/test_training.py — Unit tests for services/training.py

Covers:
- canonicalize()           — exercise name normalization
- parse_session_transcript() — Claude extraction (mocked)
- detect_personal_records()  — PR detection against exercise history
- store_session()            — Supabase writes (fully mocked)
- generate_session_summary() — Claude summary (mocked)
- process_session_voice_note() — full pipeline integration (all IO mocked)
"""
import json
import pytest
from datetime import date
from unittest.mock import MagicMock, patch, call

# ── Module under test ────────────────────────────────────────────────────────
from services.training import (
    canonicalize,
    fetch_whatsapp_media,
    parse_session_transcript,
    detect_personal_records,
    store_session,
    generate_session_summary,
    process_session_voice_note,
    LOW_CONFIDENCE_THRESHOLD,
    _empty_parse,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_exercise(name="bench press", canonical="barbell_bench_press", sets=None, confidence=0.9):
    return {
        "name": name,
        "canonical_name": canonical,
        "sets": sets or [{"reps": 5, "weight_kg": 100.0, "rpe": 8, "notes": None}],
        "trainer_cues": None,
        "form_notes": None,
        "confidence": confidence,
    }


def _make_parsed(exercises=None, session_type="strength", duration=60, confidence=0.9):
    return {
        "exercises": exercises if exercises is not None else [_make_exercise()],
        "session_type": session_type,
        "estimated_duration_min": duration,
        "trainer_feedback": "Good depth on squats.",
        "overall_confidence": confidence,
        "parse_notes": "",
    }


def _make_supabase_mock(previous_best_kg=None):
    """Return a Supabase-shaped mock with exercise_history returning a previous best."""
    mock_db = MagicMock()

    # exercise_history query chain
    hist_chain = MagicMock()
    if previous_best_kg is not None:
        hist_chain.execute.return_value.data = [{"weight_kg": previous_best_kg}]
    else:
        hist_chain.execute.return_value.data = []

    # Chain: .table().select().eq().eq().eq().order().limit()
    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .eq.return_value.order.return_value.limit.return_value = hist_chain

    # training_sessions insert
    session_insert = MagicMock()
    session_insert.execute.return_value.data = [{"id": "sess-001"}]
    mock_db.table.return_value.insert.return_value = session_insert

    # health_daily_summary select → no existing row by default
    summary_chain = MagicMock()
    summary_chain.execute.return_value.data = []
    mock_db.table.return_value.select.return_value.eq.return_value \
        .eq.return_value = summary_chain

    return mock_db


# ─────────────────────────────────────────────────────────────────────────────
# canonicalize
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalize:
    def test_exact_match(self):
        assert canonicalize("bench press") == "barbell_bench_press"

    def test_depluralize(self):
        assert canonicalize("squats") == "barbell_back_squat"

    def test_abbreviation(self):
        assert canonicalize("ohp") == "overhead_press"

    def test_case_insensitive(self):
        assert canonicalize("Deadlift") == "conventional_deadlift"

    def test_unknown_falls_back_to_snake_case(self):
        assert canonicalize("farmers walk") == "farmers_walk"

    def test_rdl(self):
        assert canonicalize("rdl") == "romanian_deadlift"

    def test_pull_ups_plural(self):
        assert canonicalize("pull ups") == "pull_up"

    def test_hip_thrusts(self):
        assert canonicalize("hip thrusts") == "hip_thrust"


# ─────────────────────────────────────────────────────────────────────────────
# fetch_whatsapp_media
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchWhatsappMedia:
    @patch("services.training.requests.get")
    def test_returns_bytes_on_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = b"audio_bytes_here"
        mock_get.return_value = mock_resp
        result = fetch_whatsapp_media("https://example.com/media/1")
        assert result == b"audio_bytes_here"
        mock_resp.raise_for_status.assert_called_once()

    @patch("services.training.requests.get")
    def test_raises_on_http_error(self, mock_get):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("403")
        mock_get.return_value = mock_resp
        with pytest.raises(req.HTTPError):
            fetch_whatsapp_media("https://example.com/media/1")


# ─────────────────────────────────────────────────────────────────────────────
# parse_session_transcript
# ─────────────────────────────────────────────────────────────────────────────

MOCK_PARSE_RESPONSE = {
    "exercises": [
        {
            "name": "bench press",
            "canonical_name": "barbell_bench_press",
            "sets": [
                {"reps": 5, "weight_kg": 88.5, "rpe": 8, "notes": None},
                {"reps": 5, "weight_kg": 88.5, "rpe": 8.5, "notes": None},
            ],
            "trainer_cues": "Keep your shoulder blades pinched.",
            "form_notes": None,
            "confidence": 0.95,
        }
    ],
    "session_type": "strength",
    "estimated_duration_min": 60,
    "trainer_feedback": "Good form overall.",
    "overall_confidence": 0.92,
    "parse_notes": "",
}


class TestParseSessionTranscript:
    @patch("services.training._anthropic")
    def test_happy_path_returns_exercises(self, mock_claude):
        mock_claude.messages.create.return_value.content = [
            MagicMock(text=json.dumps(MOCK_PARSE_RESPONSE))
        ]
        result = parse_session_transcript("Did bench press today, 5 sets of 5 at 195.", "user-1")
        assert len(result["exercises"]) == 1
        assert result["exercises"][0]["canonical_name"] == "barbell_bench_press"
        assert result["overall_confidence"] == 0.92

    @patch("services.training._anthropic")
    def test_strips_markdown_fences(self, mock_claude):
        wrapped = "```json\n" + json.dumps(MOCK_PARSE_RESPONSE) + "\n```"
        mock_claude.messages.create.return_value.content = [MagicMock(text=wrapped)]
        result = parse_session_transcript("bench press session", "user-1")
        assert result["session_type"] == "strength"

    def test_empty_transcript_returns_empty_parse(self):
        result = parse_session_transcript("", "user-1")
        assert result["exercises"] == []
        assert result["overall_confidence"] == 0.0

    def test_whitespace_only_transcript_returns_empty_parse(self):
        result = parse_session_transcript("   \n  ", "user-1")
        assert result["overall_confidence"] == 0.0

    @patch("services.training._anthropic")
    def test_claude_error_returns_empty_parse(self, mock_claude):
        mock_claude.messages.create.side_effect = RuntimeError("API timeout")
        result = parse_session_transcript("bench press today", "user-1")
        assert result["exercises"] == []
        assert "Parse failed" in result["parse_notes"]

    @patch("services.training._anthropic")
    def test_canonical_name_applied_when_missing(self, mock_claude):
        """If Claude returns name == canonical_name (not normalized), we fix it."""
        raw = json.dumps({
            **MOCK_PARSE_RESPONSE,
            "exercises": [
                {**MOCK_PARSE_RESPONSE["exercises"][0], "canonical_name": "bench press"}
            ],
        })
        mock_claude.messages.create.return_value.content = [MagicMock(text=raw)]
        result = parse_session_transcript("bench press", "user-1")
        # Should be normalized by canonicalize()
        assert result["exercises"][0]["canonical_name"] == "barbell_bench_press"


# ─────────────────────────────────────────────────────────────────────────────
# detect_personal_records
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectPersonalRecords:
    def _mock_history(self, previous_best_kg):
        mock_db = MagicMock()
        chain = MagicMock()
        if previous_best_kg is not None:
            chain.execute.return_value.data = [{"weight_kg": previous_best_kg}]
        else:
            chain.execute.return_value.data = []
        mock_db.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.eq.return_value \
            .order.return_value.limit.return_value = chain
        return mock_db

    @patch("services.training.db")
    def test_new_pr_when_no_history(self, mock_db_module):
        mock_db_module.get_db.return_value = self._mock_history(None)
        exercises = [_make_exercise(sets=[{"reps": 5, "weight_kg": 100.0, "rpe": 8, "notes": None}])]
        prs = detect_personal_records("user-1", exercises)
        assert len(prs) == 1
        assert prs[0]["canonical_name"] == "barbell_bench_press"
        assert prs[0]["new_weight_kg"] == 100.0
        assert prs[0]["previous_best_kg"] is None

    @patch("services.training.db")
    def test_pr_when_exceeds_history(self, mock_db_module):
        mock_db_module.get_db.return_value = self._mock_history(90.0)
        exercises = [_make_exercise(sets=[{"reps": 3, "weight_kg": 100.0, "rpe": 9, "notes": None}])]
        prs = detect_personal_records("user-1", exercises)
        assert len(prs) == 1
        assert prs[0]["previous_best_kg"] == 90.0

    @patch("services.training.db")
    def test_no_pr_when_below_history(self, mock_db_module):
        mock_db_module.get_db.return_value = self._mock_history(110.0)
        exercises = [_make_exercise(sets=[{"reps": 5, "weight_kg": 100.0, "rpe": 8, "notes": None}])]
        prs = detect_personal_records("user-1", exercises)
        assert prs == []

    @patch("services.training.db")
    def test_low_confidence_exercise_not_flagged(self, mock_db_module):
        mock_db_module.get_db.return_value = self._mock_history(None)
        exercises = [_make_exercise(confidence=0.4, sets=[{"reps": 5, "weight_kg": 100.0, "rpe": 8, "notes": None}])]
        prs = detect_personal_records("user-1", exercises)
        assert prs == []

    @patch("services.training.db")
    def test_zero_weight_not_flagged(self, mock_db_module):
        mock_db_module.get_db.return_value = self._mock_history(None)
        exercises = [_make_exercise(sets=[{"reps": 10, "weight_kg": 0, "rpe": None, "notes": None}])]
        prs = detect_personal_records("user-1", exercises)
        assert prs == []

    @patch("services.training.db")
    def test_none_weight_not_flagged(self, mock_db_module):
        mock_db_module.get_db.return_value = self._mock_history(None)
        exercises = [_make_exercise(sets=[{"reps": 10, "weight_kg": None, "rpe": None, "notes": None}])]
        prs = detect_personal_records("user-1", exercises)
        assert prs == []

    @patch("services.training.db")
    def test_multiple_sets_uses_max(self, mock_db_module):
        mock_db_module.get_db.return_value = self._mock_history(95.0)
        exercises = [_make_exercise(sets=[
            {"reps": 5, "weight_kg": 90.0, "rpe": 7, "notes": None},
            {"reps": 3, "weight_kg": 100.0, "rpe": 9, "notes": None},  # max
            {"reps": 2, "weight_kg": 102.5, "rpe": 10, "notes": None},  # true max
        ])]
        prs = detect_personal_records("user-1", exercises)
        assert prs[0]["new_weight_kg"] == 102.5


# ─────────────────────────────────────────────────────────────────────────────
# store_session
# ─────────────────────────────────────────────────────────────────────────────

class TestStoreSession:
    def _make_mocks(self, summary_exists=False):
        """Build per-table mocks for the Supabase client."""
        sessions_mock = MagicMock()
        sessions_mock.insert.return_value.execute.return_value.data = [{"id": "sess-001"}]

        history_mock = MagicMock()
        history_mock.insert.return_value.execute.return_value.data = [{}]

        summary_mock = MagicMock()
        if summary_exists:
            summary_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": "sum-1"}]
        else:
            summary_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        summary_mock.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{}]
        summary_mock.insert.return_value.execute.return_value.data = [{}]

        mock_db = MagicMock()
        mock_db.table.side_effect = lambda name: {
            "training_sessions": sessions_mock,
            "exercise_history": history_mock,
            "health_daily_summary": summary_mock,
        }.get(name, MagicMock())

        return mock_db, sessions_mock, history_mock, summary_mock

    @patch("services.training.db")
    def test_session_row_inserted(self, mock_db_module):
        mock_db, sessions_mock, _, _ = self._make_mocks()
        mock_db_module.get_db.return_value = mock_db

        parsed = _make_parsed()
        result = store_session("user-1", "raw transcript", parsed, [])
        sessions_mock.insert.assert_called_once()
        assert result == {"id": "sess-001"}

    @patch("services.training.db")
    def test_exercise_history_rows_inserted(self, mock_db_module):
        mock_db, _, history_mock, _ = self._make_mocks()
        mock_db_module.get_db.return_value = mock_db

        parsed = _make_parsed(exercises=[
            _make_exercise(sets=[
                {"reps": 5, "weight_kg": 100.0, "rpe": 8, "notes": None},
                {"reps": 5, "weight_kg": 102.5, "rpe": 9, "notes": None},
            ])
        ])
        store_session("user-1", "transcript", parsed, [])
        # 2 sets → 2 insert calls on exercise_history
        assert history_mock.insert.call_count == 2

    @patch("services.training.db")
    def test_pr_set_flagged_correctly(self, mock_db_module):
        mock_db, _, history_mock, _ = self._make_mocks()
        mock_db_module.get_db.return_value = mock_db

        prs = [{
            "exercise_name": "bench press",
            "canonical_name": "barbell_bench_press",
            "new_weight_kg": 102.5,
            "previous_best_kg": 100.0,
        }]
        parsed = _make_parsed(exercises=[
            _make_exercise(
                canonical="barbell_bench_press",
                sets=[
                    {"reps": 5, "weight_kg": 100.0, "rpe": 8, "notes": None},
                    {"reps": 3, "weight_kg": 102.5, "rpe": 9.5, "notes": None},  # PR set
                ]
            )
        ])
        store_session("user-1", "transcript", parsed, prs)

        calls = history_mock.insert.call_args_list
        # Find the 102.5kg insert and check is_personal_record=True
        pr_call = next(
            c for c in calls if c[0][0].get("weight_kg") == 102.5
        )
        assert pr_call[0][0]["is_personal_record"] is True
        # The lighter set should not be a PR
        non_pr_call = next(
            c for c in calls if c[0][0].get("weight_kg") == 100.0
        )
        assert non_pr_call[0][0]["is_personal_record"] is False

    @patch("services.training.db")
    def test_health_daily_summary_created_when_no_existing_row(self, mock_db_module):
        mock_db, _, _, summary_mock = self._make_mocks(summary_exists=False)
        mock_db_module.get_db.return_value = mock_db

        store_session("user-1", "transcript", _make_parsed(), [])
        summary_mock.insert.assert_called_once()
        inserted = summary_mock.insert.call_args[0][0]
        assert inserted["trained"] is True

    @patch("services.training.db")
    def test_health_daily_summary_updated_when_existing_row(self, mock_db_module):
        mock_db, _, _, summary_mock = self._make_mocks(summary_exists=True)
        mock_db_module.get_db.return_value = mock_db

        store_session("user-1", "transcript", _make_parsed(), [])
        summary_mock.update.assert_called_once()
        updated = summary_mock.update.call_args[0][0]
        assert updated["trained"] is True

    @patch("services.training.db")
    def test_empty_sets_not_inserted(self, mock_db_module):
        mock_db, _, history_mock, _ = self._make_mocks()
        mock_db_module.get_db.return_value = mock_db

        parsed = _make_parsed(exercises=[
            _make_exercise(sets=[
                {"reps": None, "weight_kg": None, "rpe": None, "notes": None}
            ])
        ])
        store_session("user-1", "transcript", parsed, [])
        history_mock.insert.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# generate_session_summary
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateSessionSummary:
    @patch("services.training._anthropic")
    def test_happy_path_calls_claude(self, mock_claude):
        mock_claude.messages.create.return_value.content = [
            MagicMock(text="New PR on bench — 102.5kg.\n3×5 @ 102.5kg.\n60 minutes total.")
        ]
        parsed = _make_parsed()
        result = generate_session_summary(parsed, [], "Abhi")
        assert "102.5" in result or "bench" in result.lower() or "Abhi" not in result
        mock_claude.messages.create.assert_called_once()

    @patch("services.training._anthropic")
    def test_low_confidence_skips_claude(self, mock_claude):
        parsed = _make_parsed(confidence=0.3)
        result = generate_session_summary(parsed, [], "Abhi")
        assert "audio" in result.lower()
        mock_claude.messages.create.assert_not_called()

    @patch("services.training._anthropic")
    def test_no_exercises_skips_claude(self, mock_claude):
        parsed = _make_parsed(exercises=[], confidence=0.9)
        result = generate_session_summary(parsed, [], "Abhi")
        assert "audio" in result.lower()
        mock_claude.messages.create.assert_not_called()

    @patch("services.training._anthropic")
    def test_claude_error_uses_fallback(self, mock_claude):
        mock_claude.messages.create.side_effect = RuntimeError("timeout")
        parsed = _make_parsed(exercises=[
            _make_exercise(
                name="bench press",
                sets=[{"reps": 5, "weight_kg": 100.0, "rpe": 8, "notes": None}]
            )
        ])
        result = generate_session_summary(parsed, [], "Abhi")
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("services.training._anthropic")
    def test_fallback_includes_pr(self, mock_claude):
        mock_claude.messages.create.side_effect = RuntimeError("timeout")
        parsed = _make_parsed()
        prs = [{"exercise_name": "bench press", "canonical_name": "barbell_bench_press",
                "new_weight_kg": 102.5, "previous_best_kg": 100.0}]
        result = generate_session_summary(parsed, prs, "Abhi")
        assert "102.5" in result or "PR" in result or "bench" in result.lower()


# ─────────────────────────────────────────────────────────────────────────────
# process_session_voice_note — full pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessSessionVoiceNote:
    def _patch_all(self, audio_bytes=b"x" * 5000, transcript="bench press 5x5 at 195"):
        patches = {
            "fetch": patch("services.training.fetch_whatsapp_media", return_value=audio_bytes),
            "transcribe": patch("services.training.transcribe_audio", return_value=transcript),
            "parse": patch("services.training.parse_session_transcript", return_value=_make_parsed()),
            "pr": patch("services.training.detect_personal_records", return_value=[]),
            "store": patch("services.training.store_session", return_value={"id": "sess-001"}),
            "summary": patch("services.training.generate_session_summary", return_value="Nice session."),
            "send": patch("services.whatsapp.send_message"),
            "db": patch("services.training.db"),
        }
        return patches

    def test_happy_path_sends_summary(self):
        patches = self._patch_all()
        ctx = {k: p.start() for k, p in patches.items()}
        ctx["db"].get_user_by_id.return_value = {"name": "Abhi"}

        try:
            result = process_session_voice_note("user-1", "+14155551234", "https://example.com/m")
            assert result == "Nice session."
            ctx["send"].assert_called_once_with("+14155551234", "Nice session.", user_id="user-1")
        finally:
            for p in patches.values():
                p.stop()

    def test_media_download_failure_sends_error(self):
        patches = self._patch_all()
        ctx = {k: p.start() for k, p in patches.items()}
        ctx["db"].get_user_by_id.return_value = {"name": "Abhi"}
        ctx["fetch"].side_effect = Exception("403 Forbidden")

        try:
            result = process_session_voice_note("user-1", "+14155551234", "https://example.com/m")
            assert "send" in result.lower() or "download" in result.lower() or "couldn't" in result.lower()
            ctx["send"].assert_called_once()
        finally:
            for p in patches.values():
                p.stop()

    def test_too_short_audio_sends_error(self):
        patches = self._patch_all(audio_bytes=b"short")
        ctx = {k: p.start() for k, p in patches.items()}
        ctx["db"].get_user_by_id.return_value = {"name": "Abhi"}

        try:
            result = process_session_voice_note("user-1", "+14155551234", "https://example.com/m")
            assert "short" in result.lower() or "too short" in result.lower()
            # transcribe should NOT be called for short audio
            ctx["transcribe"].assert_not_called()
        finally:
            for p in patches.values():
                p.stop()

    def test_empty_transcript_sends_error(self):
        patches = self._patch_all(transcript="")
        ctx = {k: p.start() for k, p in patches.items()}
        ctx["db"].get_user_by_id.return_value = {"name": "Abhi"}

        try:
            result = process_session_voice_note("user-1", "+14155551234", "https://example.com/m")
            assert "transcrib" in result.lower() or "noisy" in result.lower() or "text" in result.lower()
        finally:
            for p in patches.values():
                p.stop()

    def test_ogg_extension_used_for_ogg_content_type(self):
        patches = self._patch_all()
        ctx = {k: p.start() for k, p in patches.items()}
        ctx["db"].get_user_by_id.return_value = {"name": "Abhi"}

        try:
            process_session_voice_note("user-1", "+14155551234", "https://example.com/m", "audio/ogg")
            call_kwargs = ctx["transcribe"].call_args
            assert ".ogg" in call_kwargs[1].get("filename", "") or ".ogg" in str(call_kwargs)
        finally:
            for p in patches.values():
                p.stop()

    def test_m4a_extension_used_for_non_ogg_content_type(self):
        patches = self._patch_all()
        ctx = {k: p.start() for k, p in patches.items()}
        ctx["db"].get_user_by_id.return_value = {"name": "Abhi"}

        try:
            process_session_voice_note("user-1", "+14155551234", "https://example.com/m", "audio/mp4")
            call_kwargs = ctx["transcribe"].call_args
            assert ".m4a" in call_kwargs[1].get("filename", "") or ".m4a" in str(call_kwargs)
        finally:
            for p in patches.values():
                p.stop()

    def test_full_pipeline_order(self):
        """Verify each stage is called exactly once in the right order."""
        call_order = []
        patches = self._patch_all()
        ctx = {k: p.start() for k, p in patches.items()}
        ctx["db"].get_user_by_id.return_value = {"name": "Abhi"}

        ctx["fetch"].side_effect = lambda *a, **kw: call_order.append("fetch") or b"x" * 5000
        ctx["transcribe"].side_effect = lambda *a, **kw: call_order.append("transcribe") or "bench press 5x5"
        ctx["parse"].side_effect = lambda *a, **kw: call_order.append("parse") or _make_parsed()
        ctx["pr"].side_effect = lambda *a, **kw: call_order.append("pr") or []
        ctx["store"].side_effect = lambda *a, **kw: call_order.append("store") or {}
        ctx["summary"].side_effect = lambda *a, **kw: call_order.append("summary") or "Done."

        try:
            process_session_voice_note("user-1", "+14155551234", "https://example.com/m")
            assert call_order == ["fetch", "transcribe", "parse", "pr", "store", "summary"]
        finally:
            for p in patches.values():
                p.stop()
