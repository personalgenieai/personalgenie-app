"""
routers/trainer.py — Personal trainer session access.

The training.py service handles WhatsApp-based session capture.
This router exposes training data to the iOS app.
"""
import logging
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import get_settings
from routers.auth import verify_app_token
import database as db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trainer", tags=["trainer"])


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_user_id(request: Request) -> str:
    token = request.headers.get("X-App-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-App-Token")
    payload = verify_app_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]


# ── Pydantic models ───────────────────────────────────────────────────────────

class SetLog(BaseModel):
    reps: Optional[int] = None
    weight_kg: Optional[float] = None


class ExerciseLog(BaseModel):
    name: str
    sets: List[SetLog]


class LogSessionRequest(BaseModel):
    user_id: str
    exercises: List[ExerciseLog]
    notes: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/sessions/{user_id}")
async def get_sessions(user_id: str, request: Request):
    """
    Return the last 30 training sessions for a user.
    Pulls from training_sessions and joins exercise data from exercise_history.
    """
    _get_user_id(request)

    try:
        supabase = db.get_db()

        sessions_result = (
            supabase.table("training_sessions")
            .select(
                "id, session_date, duration_minutes, exercises, trainer_feedback, "
                "personal_records, session_type"
            )
            .eq("user_id", user_id)
            .order("session_date", desc=True)
            .limit(30)
            .execute()
        )
        sessions = sessions_result.data or []

        import json as _json

        output = []
        for s in sessions:
            raw_exercises = s.get("exercises")
            if isinstance(raw_exercises, str):
                try:
                    raw_exercises = _json.loads(raw_exercises)
                except Exception:
                    raw_exercises = []
            raw_exercises = raw_exercises or []

            # Normalize exercise structure for the iOS response
            exercises_out = []
            for ex in raw_exercises:
                sets_out = []
                for st in ex.get("sets", []):
                    sets_out.append({
                        "reps": st.get("reps"),
                        "weight_kg": st.get("weight_kg"),
                    })
                exercises_out.append({
                    "name": ex.get("name") or ex.get("canonical_name", ""),
                    "sets": sets_out,
                })

            # Pull trainer notes from trainer_feedback JSONB
            raw_feedback = s.get("trainer_feedback")
            if isinstance(raw_feedback, str):
                try:
                    raw_feedback = _json.loads(raw_feedback)
                except Exception:
                    raw_feedback = {}
            trainer_notes = (raw_feedback or {}).get("notes") if raw_feedback else None

            # Estimate calories from session type and duration (rough heuristic)
            duration = s.get("duration_minutes")
            session_type = s.get("session_type", "strength")
            calories = None
            if duration:
                rate = {"strength": 6, "cardio": 9, "mobility": 3, "mixed": 7}.get(session_type, 6)
                calories = int(duration * rate)

            output.append({
                "id": s["id"],
                "session_date": s.get("session_date"),
                "duration_minutes": duration,
                "exercises": exercises_out,
                "summary": trainer_notes,
                "trainer_notes": trainer_notes,
                "calories_burned": calories,
            })

        return {"sessions": output}

    except Exception as exc:
        logger.error("Failed to fetch sessions for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Could not fetch sessions")


@router.get("/exercise/{user_id}/{exercise_name}")
async def get_exercise_history(user_id: str, exercise_name: str, request: Request):
    """
    Return progressive overload chart data for a specific exercise.
    Aggregates max weight, total volume, and set count per session date.
    Sorted by date ascending for chart rendering.
    """
    _get_user_id(request)

    try:
        from services.training import canonicalize
        supabase = db.get_db()

        canonical = canonicalize(exercise_name)

        # Pull all sets for this exercise (by canonical name or spoken name)
        history_result = (
            supabase.table("exercise_history")
            .select("weight_kg, reps, set_number, training_sessions(session_date)")
            .eq("user_id", user_id)
            .eq("exercise_canonical_name", canonical)
            .order("training_sessions(session_date)", desc=False)
            .execute()
        )
        rows = history_result.data or []

        # Group by session date
        by_date: dict = {}
        for row in rows:
            session = row.get("training_sessions") or {}
            session_date = session.get("session_date") if isinstance(session, dict) else None
            if not session_date:
                continue
            weight = row.get("weight_kg") or 0
            reps = row.get("reps") or 0
            if session_date not in by_date:
                by_date[session_date] = {"max_weight_kg": 0, "total_volume": 0, "sets_count": 0}
            entry = by_date[session_date]
            if weight > entry["max_weight_kg"]:
                entry["max_weight_kg"] = weight
            entry["total_volume"] += weight * reps
            entry["sets_count"] += 1

        history_out = [
            {"date": d, **v}
            for d, v in sorted(by_date.items())
        ]

        return {"exercise_name": exercise_name, "history": history_out}

    except Exception as exc:
        logger.error("Failed to fetch exercise history for user %s / %s: %s", user_id, exercise_name, exc)
        raise HTTPException(status_code=500, detail="Could not fetch exercise history")


@router.get("/stats/{user_id}")
async def get_trainer_stats(user_id: str, request: Request):
    """
    Return summary training stats for a user:
    - Sessions this week and this month
    - Favorite exercise (by frequency)
    - Total volume this month
    - Personal records per exercise
    """
    _get_user_id(request)

    try:
        import json as _json
        from datetime import timedelta
        supabase = db.get_db()

        now = datetime.now(timezone.utc)
        start_of_week = (now - timedelta(days=now.weekday())).date().isoformat()
        start_of_month = now.date().replace(day=1).isoformat()

        # Sessions this month
        month_result = (
            supabase.table("training_sessions")
            .select("id, session_date, exercises, personal_records, duration_minutes")
            .eq("user_id", user_id)
            .gte("session_date", start_of_month)
            .execute()
        )
        month_sessions = month_result.data or []

        sessions_this_month = len(month_sessions)
        sessions_this_week = sum(
            1 for s in month_sessions if (s.get("session_date") or "") >= start_of_week
        )

        # Favorite exercise and total volume this month
        exercise_counts: dict = {}
        total_volume = 0.0
        for s in month_sessions:
            raw = s.get("exercises")
            if isinstance(raw, str):
                try:
                    raw = _json.loads(raw)
                except Exception:
                    raw = []
            for ex in (raw or []):
                name = ex.get("name") or ex.get("canonical_name", "")
                if name:
                    exercise_counts[name] = exercise_counts.get(name, 0) + 1
                for st in ex.get("sets", []):
                    w = st.get("weight_kg") or 0
                    r = st.get("reps") or 0
                    total_volume += w * r

        favorite_exercise = max(exercise_counts, key=exercise_counts.get) if exercise_counts else None

        # Personal records (all time) from exercise_history
        pr_result = (
            supabase.table("exercise_history")
            .select("exercise_name, weight_kg, training_sessions(session_date)")
            .eq("user_id", user_id)
            .eq("is_personal_record", True)
            .order("weight_kg", desc=True)
            .execute()
        )
        pr_rows = pr_result.data or []

        # Deduplicate: keep only the best PR per exercise
        seen_exercises: set = set()
        personal_records = []
        for row in pr_rows:
            name = row.get("exercise_name", "")
            if name in seen_exercises:
                continue
            seen_exercises.add(name)
            session = row.get("training_sessions") or {}
            session_date = session.get("session_date") if isinstance(session, dict) else None
            personal_records.append({
                "exercise": name,
                "weight_kg": row.get("weight_kg"),
                "date": session_date,
            })

        return {
            "sessions_this_month": sessions_this_month,
            "sessions_this_week": sessions_this_week,
            "favorite_exercise": favorite_exercise,
            "total_volume_this_month": round(total_volume, 1),
            "personal_records": personal_records,
        }

    except Exception as exc:
        logger.error("Failed to fetch trainer stats for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Could not fetch trainer stats")


@router.post("/session")
async def log_session_manually(request: Request, body: LogSessionRequest):
    """
    Manually log a training session from the iOS app.
    Inserts a training_sessions row and exercise_history rows per set.
    PR detection is run automatically.
    """
    _get_user_id(request)

    user = db.get_user_by_id(body.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        from services.training import detect_personal_records, store_session
        import json as _json

        # Convert pydantic models → dicts in the shape store_session expects
        exercises_dicts = []
        for ex in body.exercises:
            sets_dicts = [{"reps": s.reps, "weight_kg": s.weight_kg} for s in ex.sets]
            exercises_dicts.append({
                "name": ex.name,
                "canonical_name": ex.name.lower().replace(" ", "_"),
                "sets": sets_dicts,
                "trainer_cues": None,
                "form_notes": None,
                "confidence": 1.0,
            })

        parsed = {
            "exercises": exercises_dicts,
            "session_type": "strength",
            "estimated_duration_min": None,
            "trainer_feedback": body.notes,
            "overall_confidence": 1.0,
            "parse_notes": "manually logged via iOS app",
        }

        prs = detect_personal_records(body.user_id, exercises_dicts)
        session_row = store_session(
            user_id=body.user_id,
            transcript="",
            parsed=parsed,
            prs=prs,
        )

        return {
            "status": "logged",
            "session_id": session_row.get("id"),
            "personal_records": [
                {"exercise": p["exercise_name"], "weight_kg": p["new_weight_kg"]}
                for p in prs
            ],
        }

    except Exception as exc:
        logger.error("Failed to log manual session for user %s: %s", body.user_id, exc)
        raise HTTPException(status_code=500, detail="Could not log session")
