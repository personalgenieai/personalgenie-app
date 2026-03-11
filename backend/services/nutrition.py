"""
services/nutrition.py — Health Genie: food intake parsing and logging.

Handles everything from receiving a casual food description ("just had eggs and toast")
to storing structured nutrition data and generating a brief acknowledgment.

Design principles:
- Any input format works: text, voice transcript, vague descriptions
- Genie does the work — user does the minimum
- Silent logging after habit is established (7 days)
- Never lecture on food choices — numbers only, and only when worth surfacing
- Midnight cutoff: logs before 3am count toward the previous day
"""
import json
import logging
import re
from datetime import datetime, date, timedelta, timezone
from typing import Optional

from anthropic import Anthropic
from config import get_settings
import database as db

logger = logging.getLogger(__name__)
settings = get_settings()

_anthropic = Anthropic(api_key=settings.anthropic_api_key)

# After this many days logging, switch from always-ack to significance-gated ack
HABIT_BUILDING_DAYS = 7

# Only surface an acknowledgment if significance score crosses this threshold
SIGNIFICANCE_THRESHOLD = 0.5

# Keywords that indicate a food log intent (fast pre-check before Claude)
_FOOD_SIGNALS = [
    "had ", "ate ", "just had", "just ate", "just finished",
    "for breakfast", "for lunch", "for dinner", "for brunch", "for snack",
    "breakfast", "lunch", "dinner", "snack", "brunch",
    "eating ", "drank ", "drink ", "drinking ",
    "coffee", "tea", "juice", "smoothie", "protein shake",
    "calories", " cal ", "macros", "protein",
    "ordered ", "grabbed ", "picked up ",
]

# Keywords that strongly indicate a session trigger (not food)
_SESSION_SIGNALS = ["starting session", "start session", "session start", "gym session"]


# ── Intent detection ──────────────────────────────────────────────────────────

def is_food_intent(text: str) -> bool:
    """
    Quick keyword check — is this message likely a food log?
    Called before the main Claude conversation to route appropriately.
    Does not use an API call — must be fast.
    """
    t = text.lower().strip()
    # Session signals take priority — don't misclassify
    if any(s in t for s in _SESSION_SIGNALS):
        return False
    return any(s in t for s in _FOOD_SIGNALS)


def is_session_trigger(text: str) -> bool:
    """
    Detect 'starting session' trigger for training session flow.
    Option B: user explicitly signals before sending voice note.
    """
    t = text.lower().strip()
    return any(s in t for s in _SESSION_SIGNALS)


# ── Date helpers ──────────────────────────────────────────────────────────────

def _effective_date(user_tz_offset: int = 0) -> date:
    """
    Determine which date a log entry belongs to.
    Midnight rule: anything before 3am counts toward the previous day.
    user_tz_offset: hours from UTC (e.g. -8 for SF). Default 0 = UTC.
    """
    now_utc = datetime.now(timezone.utc)
    local_hour = (now_utc.hour + user_tz_offset) % 24
    local_date = (now_utc + timedelta(hours=user_tz_offset)).date()
    if local_hour < 3:
        return local_date - timedelta(days=1)
    return local_date


def _infer_meal_type(user_tz_offset: int = 0) -> str:
    """Infer meal type from local time of day."""
    now_utc = datetime.now(timezone.utc)
    local_hour = (now_utc.hour + user_tz_offset) % 24
    if 5 <= local_hour < 10:
        return "breakfast"
    if 10 <= local_hour < 14:
        return "lunch"
    if 14 <= local_hour < 17:
        return "snack"
    if 17 <= local_hour < 21:
        return "dinner"
    return "snack"


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_food_input(raw_input: str, input_type: str = "text") -> dict:
    """
    Parse any food description into structured nutrition data.

    Returns:
        {
            foods: [{name, quantity, unit, calories, protein_g, carbs_g, fat_g, confidence}],
            total_calories: float,
            total_protein: float,
            total_carbs: float,
            total_fat: float,
            overall_confidence: float,   # 0.0–1.0
            clarification_question: str | None,
            meal_type_hint: str | None,
            parsing_notes: str,
        }
    """
    prompt = f"""Parse this food log entry into structured nutrition data.

Input ({input_type}): "{raw_input}"

Rules:
- Use realistic restaurant portion sizes, not ideal portions
- Lean toward what people actually eat, not diet-book servings
- A "burrito bowl" at Chipotle is ~750–900 cal, not 400
- A "burrito" is ~1000 cal
- If the input is a voice transcript, extract the food parts only
- If genuinely ambiguous (e.g. "coffee" — black? with milk and sugar?), set confidence < 0.6
  and provide a single clarification_question
- If vague but interpretable ("some chips"), use a middle estimate and note it
- For multiple items in one message, parse each separately

Return ONLY valid JSON in this exact format:
{{
  "foods": [
    {{
      "name": "string",
      "quantity": number,
      "unit": "string",
      "calories": number,
      "protein_g": number,
      "carbs_g": number,
      "fat_g": number,
      "confidence": number
    }}
  ],
  "total_calories": number,
  "total_protein": number,
  "total_carbs": number,
  "total_fat": number,
  "overall_confidence": number,
  "clarification_question": "string or null",
  "meal_type_hint": "breakfast|lunch|dinner|snack|null",
  "parsing_notes": "string"
}}"""

    try:
        response = _anthropic.messages.create(
            model=settings.claude_model,
            max_tokens=600,
            system="You are a nutrition parser. Return only valid JSON. Never explain or add prose.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if Claude wraps in them
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        return json.loads(raw)

    except Exception as e:
        logger.error(f"Food parse error: {e}")
        # Return a safe fallback — log the attempt without nutrition data
        return {
            "foods": [],
            "total_calories": 0,
            "total_protein": 0,
            "total_carbs": 0,
            "total_fat": 0,
            "overall_confidence": 0.0,
            "clarification_question": "What did you have? I want to make sure I log it right.",
            "meal_type_hint": None,
            "parsing_notes": f"Parse failed: {e}",
        }


# ── Storage ───────────────────────────────────────────────────────────────────

def store_food_log(
    user_id: str,
    raw_input: str,
    parsed: dict,
    input_type: str = "text",
    user_tz_offset: int = 0,
) -> dict:
    """
    Write to nutrition_log and upsert health_daily_summary.
    Returns the updated daily summary row.
    """
    supabase = db.get_db()
    log_date = _effective_date(user_tz_offset)
    meal_type = parsed.get("meal_type_hint") or _infer_meal_type(user_tz_offset)

    # Insert log entry
    supabase.table("nutrition_log").insert({
        "user_id": user_id,
        "meal_type": meal_type,
        "raw_input": raw_input[:1000],
        "input_type": input_type,
        "parsed_foods": json.dumps(parsed.get("foods", [])),
        "total_calories": parsed.get("total_calories", 0),
        "total_protein": parsed.get("total_protein", 0),
        "total_carbs": parsed.get("total_carbs", 0),
        "total_fat": parsed.get("total_fat", 0),
        "parsing_confidence": parsed.get("overall_confidence", 1.0),
        "genie_clarified": bool(parsed.get("clarification_question")),
    }).execute()

    # Upsert daily summary — increment running totals
    existing = (
        supabase.table("health_daily_summary")
        .select("*")
        .eq("user_id", user_id)
        .eq("summary_date", log_date.isoformat())
        .execute()
    )

    if existing.data:
        row = existing.data[0]
        updated = supabase.table("health_daily_summary").update({
            "total_calories": (row["total_calories"] or 0) + parsed.get("total_calories", 0),
            "total_protein": (row["total_protein"] or 0) + parsed.get("total_protein", 0),
        }).eq("user_id", user_id).eq("summary_date", log_date.isoformat()).execute()
        return updated.data[0] if updated.data else row
    else:
        new_row = supabase.table("health_daily_summary").insert({
            "user_id": user_id,
            "summary_date": log_date.isoformat(),
            "total_calories": parsed.get("total_calories", 0),
            "total_protein": parsed.get("total_protein", 0),
        }).execute()
        return new_row.data[0] if new_row.data else {}


def get_daily_summary(user_id: str, for_date: Optional[date] = None) -> dict:
    """Return today's health_daily_summary row, or an empty dict if none exists."""
    supabase = db.get_db()
    target = for_date or _effective_date()
    result = (
        supabase.table("health_daily_summary")
        .select("*")
        .eq("user_id", user_id)
        .eq("summary_date", target.isoformat())
        .execute()
    )
    return result.data[0] if result.data else {}


def get_days_logging(user_id: str) -> int:
    """Count how many distinct dates the user has logged food."""
    supabase = db.get_db()
    result = (
        supabase.table("health_daily_summary")
        .select("summary_date")
        .eq("user_id", user_id)
        .gt("total_calories", 0)
        .execute()
    )
    return len(result.data) if result.data else 0


# ── Acknowledgment ────────────────────────────────────────────────────────────

def _significance_score(parsed: dict, daily: dict) -> float:
    """
    Score 0.0–1.0: how noteworthy is this log entry given today's running total?
    High score = worth surfacing to user. Low score = log silently.
    """
    score = 0.0
    cal_goal = daily.get("calorie_goal") or 2000
    total_cal = daily.get("total_calories", 0)
    this_cal = parsed.get("total_calories", 0)

    # Substantially over daily goal
    if total_cal > cal_goal * 1.25:
        score += 0.6

    # Low protein relative to goal after dinner
    protein_goal = daily.get("protein_goal") or 150
    total_protein = daily.get("total_protein", 0)
    hour = datetime.now(timezone.utc).hour
    if hour >= 20 and total_protein < protein_goal * 0.6:
        score += 0.5

    # Very large single entry (>600 cal)
    if this_cal > 600:
        score += 0.3

    return min(score, 1.0)


def build_acknowledgment(
    parsed: dict,
    daily: dict,
    days_logging: int,
) -> Optional[str]:
    """
    Return a brief acknowledgment string, or None if Genie should log silently.

    Week 1 (habit-building): always acknowledge.
    After week 1: only acknowledge if significance score crosses threshold.

    Never lectures. Numbers only. One line maximum.
    """
    cal = parsed.get("total_calories", 0)
    protein = parsed.get("total_protein", 0)
    total_cal_today = daily.get("total_calories", 0)

    # If parse failed or empty, return clarification question instead
    if not parsed.get("foods") and parsed.get("clarification_question"):
        return parsed["clarification_question"]

    if days_logging < HABIT_BUILDING_DAYS:
        # Always acknowledge during habit-building phase
        if total_cal_today > 0:
            return f"~{round(cal)} cal, {round(protein)}g protein. At {round(total_cal_today)} for today."
        return f"~{round(cal)} cal, {round(protein)}g protein. Good start."

    # After habit is established — only surface if significant
    score = _significance_score(parsed, daily)
    if score < SIGNIFICANCE_THRESHOLD:
        return None  # Log silently

    cal_goal = daily.get("calorie_goal") or 2000
    total_cal_today = daily.get("total_calories", 0)
    if total_cal_today > cal_goal * 1.25:
        over = round(total_cal_today - cal_goal)
        return f"At {round(total_cal_today)} today — {over} over your goal."

    protein_goal = daily.get("protein_goal") or 150
    total_protein = daily.get("total_protein", 0)
    if total_protein < protein_goal * 0.6:
        remaining = round(protein_goal - total_protein)
        return f"{remaining}g protein still to go today."

    return None
