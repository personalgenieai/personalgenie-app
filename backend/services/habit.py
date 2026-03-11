"""
services/habit.py — Sprint 3: Habit Formation

Two responsibilities:

1. LearningQuestionsFlow
   Six questions asked one per day over the first six logging days.
   State is tracked in health_profile (pending_question_idx, last_question_date).
   Answers are parsed from free-form WhatsApp replies and stored back.

2. Weekly roll-up helpers
   Aggregate the past 7 days of food + training data into a single
   plain-English WhatsApp message sent every Sunday.
"""
import logging
import re
from datetime import date, timedelta
from typing import Optional

import database as db

logger = logging.getLogger(__name__)

# ── Learning questions ────────────────────────────────────────────────────────
# (db_field_name, question_text)
LEARNING_QUESTIONS = [
    (
        "calorie_goal",
        "One quick thing — what's your rough daily calorie target? Even a ballpark works.",
    ),
    (
        "protein_goal_g",
        "How much protein are you aiming for each day? In grams if you know it.",
    ),
    (
        "training_days_per_week",
        "How many days a week do you usually train?",
    ),
    (
        "goal_type",
        "Are you working on losing weight, gaining muscle, or mostly staying consistent?",
    ),
    (
        "food_restrictions",
        "Anything you're avoiding right now — allergies, intolerances, things you just don't eat?",
    ),
    (
        "biggest_struggle",
        "Last one. What's the hardest part of eating well for you?",
    ),
]


# ── Profile CRUD ──────────────────────────────────────────────────────────────

def get_health_profile(user_id: str) -> Optional[dict]:
    """Fetch the user's health_profile row. Returns None if not yet created."""
    try:
        result = (
            db.get_db()
            .table("health_profile")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"get_health_profile error for {user_id}: {e}")
        return None


def _upsert_health_profile(user_id: str, updates: dict) -> None:
    """Create or update the user's health_profile row."""
    try:
        supabase = db.get_db()
        existing = (
            supabase.table("health_profile")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            supabase.table("health_profile").update(updates).eq("user_id", user_id).execute()
        else:
            supabase.table("health_profile").insert({"user_id": user_id, **updates}).execute()
    except Exception as e:
        logger.error(f"_upsert_health_profile error for {user_id}: {e}")


def ensure_health_profile_exists(user_id: str) -> None:
    """
    Call when the user logs their first food entry.
    Creates the profile row if it doesn't exist yet so the learning
    questions flow has a row to update.
    """
    if not get_health_profile(user_id):
        _upsert_health_profile(user_id, {"questions_completed": 0, "last_nudge_variant_idx": -1})


# ── Learning questions flow ───────────────────────────────────────────────────

def is_awaiting_answer(user_id: str) -> bool:
    """True when Genie has asked a question and is waiting for the reply."""
    profile = get_health_profile(user_id)
    return profile is not None and profile.get("pending_question_idx") is not None


def get_next_question(user_id: str) -> Optional[tuple]:
    """
    Returns (question_idx, question_text) if there is a question to surface today.
    Returns None when:
    - All 6 questions are already answered
    - A question was already asked today
    - Still awaiting the answer to a previously asked question
    """
    profile = get_health_profile(user_id)
    if not profile:
        return None

    completed = profile.get("questions_completed", 0)
    if completed >= len(LEARNING_QUESTIONS):
        return None

    if profile.get("pending_question_idx") is not None:
        return None  # Waiting for an answer

    last_date = profile.get("last_question_date")
    if last_date == date.today().isoformat():
        return None  # Already asked one today

    return (completed, LEARNING_QUESTIONS[completed][1])


def mark_question_asked(user_id: str, question_idx: int) -> None:
    """Record that a question was surfaced. Puts the flow into pending state."""
    _upsert_health_profile(user_id, {
        "pending_question_idx": question_idx,
        "last_question_date": date.today().isoformat(),
    })


def handle_question_answer(user_id: str, raw_answer: str) -> Optional[str]:
    """
    Parse the user's free-form reply to the pending question.
    Stores the structured answer, clears pending state, and advances the counter.
    Returns a brief Genie acknowledgment, or None if there was no pending question.
    """
    profile = get_health_profile(user_id)
    if not profile:
        return None

    pending_idx = profile.get("pending_question_idx")
    if pending_idx is None:
        return None
    if pending_idx >= len(LEARNING_QUESTIONS):
        return None

    field_name, _ = LEARNING_QUESTIONS[pending_idx]
    parsed_value = _parse_answer(field_name, raw_answer)

    _upsert_health_profile(user_id, {
        field_name: parsed_value,
        "questions_completed": pending_idx + 1,
        "pending_question_idx": None,
    })

    return _answer_ack(field_name, parsed_value, pending_idx + 1)


def _parse_answer(field_name: str, raw: str) -> str:
    """
    Extract a clean value from a free-form answer.
    Numeric fields: pull the first integer found.
    goal_type: normalize to lose | gain | maintain.
    Text fields: store verbatim (capped at 200 chars).
    """
    raw = raw.strip()

    if field_name in ("calorie_goal", "protein_goal_g", "training_days_per_week"):
        match = re.search(r"\b(\d+)", raw)
        return match.group(1) if match else raw[:50]

    if field_name == "goal_type":
        lower = raw.lower()
        if any(w in lower for w in ("lose", "cut", "deficit", "weight loss", "fat loss")):
            return "lose"
        if any(w in lower for w in ("gain", "bulk", "muscle", "mass", "build")):
            return "gain"
        if any(w in lower for w in ("maintain", "consistent", "stay", "keep", "recomp")):
            return "maintain"
        return raw[:100]

    return raw[:200]


def _answer_ack(field_name: str, value: str, questions_done: int) -> str:
    """One-line Genie acknowledgment after receiving an answer."""
    acks = {
        "calorie_goal": f"Got it — {value} calories as your daily target.",
        "protein_goal_g": f"{value}g protein. Noted.",
        "training_days_per_week": f"{value} days a week. Good to know.",
        "goal_type": {
            "lose": "Understood — we're focused on a deficit.",
            "gain": "Got it — building.",
            "maintain": "Staying consistent. Makes sense.",
        }.get(value, f"Got it — {value}."),
        "food_restrictions": "Noted. I'll keep that in mind when I flag things.",
        "biggest_struggle": "Appreciate you sharing that. I'll keep it in mind.",
    }
    ack = acks.get(field_name, "Got it.")
    if questions_done >= len(LEARNING_QUESTIONS):
        ack += " That's everything I needed — I have a good picture now."
    return ack


# ── Nudge variant rotation ────────────────────────────────────────────────────

def pick_nudge_variant(variants: list, last_idx: int) -> tuple:
    """
    Pick a nudge variant that differs from the one used last time.
    Returns (new_idx, variant_text).
    Falls back to random if only one variant exists.
    """
    import random
    if len(variants) <= 1:
        return (0, variants[0])
    available = [i for i in range(len(variants)) if i != last_idx]
    idx = random.choice(available)
    return (idx, variants[idx])


def question_was_sent_today(user_id: str) -> bool:
    """True if a learning question was already sent to this user today."""
    profile = get_health_profile(user_id)
    if not profile:
        return False
    return profile.get("last_question_date") == date.today().isoformat()


def get_last_nudge_variant_idx(user_id: str) -> int:
    """Returns the index of the last nudge variant used (-1 if never nudged)."""
    profile = get_health_profile(user_id)
    if not profile:
        return -1
    return profile.get("last_nudge_variant_idx", -1)


def record_nudge_variant(user_id: str, variant_idx: int) -> None:
    """Persist which variant was just used so we don't repeat it tomorrow."""
    _upsert_health_profile(user_id, {"last_nudge_variant_idx": variant_idx})


# ── Weekly roll-up ────────────────────────────────────────────────────────────

def get_weekly_summary(user_id: str) -> dict:
    """
    Aggregate the past 7 days of food and training data from health_daily_summary.
    Returns a dict with days_logged, avg_calories, avg_protein_g, training_sessions.
    """
    try:
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        result = (
            db.get_db()
            .table("health_daily_summary")
            .select("total_calories, total_protein, trained, summary_date")
            .eq("user_id", user_id)
            .gte("summary_date", cutoff)
            .execute()
        )
        rows = result.data or []

        days_with_food = [r for r in rows if (r.get("total_calories") or 0) > 0]
        days_trained = sum(1 for r in rows if r.get("trained"))

        total_cal = sum(r.get("total_calories") or 0 for r in days_with_food)
        total_prot = sum(r.get("total_protein") or 0 for r in days_with_food)
        n = len(days_with_food)

        return {
            "days_logged": n,
            "avg_calories": round(total_cal / n, 0) if n else 0,
            "avg_protein_g": round(total_prot / n, 1) if n else 0,
            "training_sessions": days_trained,
            "total_calories": total_cal,
            "total_protein_g": total_prot,
        }
    except Exception as e:
        logger.error(f"get_weekly_summary error for {user_id}: {e}")
        return {
            "days_logged": 0, "avg_calories": 0, "avg_protein_g": 0,
            "training_sessions": 0, "total_calories": 0, "total_protein_g": 0,
        }


def build_weekly_rollup_message(summary: dict) -> Optional[str]:
    """
    Build the Sunday roll-up WhatsApp message.
    Returns None if fewer than 2 days were logged (not enough to be useful).
    """
    days = summary.get("days_logged", 0)
    if days < 2:
        return None

    avg_cal = summary.get("avg_calories", 0)
    avg_prot = summary.get("avg_protein_g", 0)
    sessions = summary.get("training_sessions", 0)

    lines = [f"This week ({days}/7 days logged):"]
    if avg_cal:
        lines.append(f"Avg {int(avg_cal)} cal/day.")
    if avg_prot:
        lines.append(f"Avg {avg_prot}g protein/day.")
    if sessions:
        lines.append(f"{sessions} training session{'s' if sessions != 1 else ''} logged.")
    elif days >= 3:
        lines.append("No training sessions logged.")

    return "\n".join(lines)
