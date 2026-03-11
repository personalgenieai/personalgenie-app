"""
services/training.py — Health Genie: training session capture and processing.

Flow (Option B trigger — Sprint 2):
  1. User says "starting session" → messages router sets session active flag
  2. User sends WhatsApp voice note when done
  3. consent webhook detects media + active session → calls process_session_voice_note()
  4. Whisper transcribes the audio
  5. Claude extracts exercises, sets, reps, weight, trainer notes, PRs
  6. Session + exercise history stored in Supabase
  7. WhatsApp summary sent before the user has showered

Design principles:
- Graceful degradation on noisy/unclear audio — never fail silently
- PR detection against actual exercise history — real numbers, not guesses
- Session summary sounds like a person who was there, not an app report
- Trainer stays central — Genie records, trainer coaches
"""
import json
import logging
import re
import requests
from datetime import date, datetime, timezone
from typing import Optional

from anthropic import Anthropic
from config import get_settings
from services.transcription import transcribe_audio
import database as db

logger = logging.getLogger(__name__)
settings = get_settings()
_anthropic = Anthropic(api_key=settings.anthropic_api_key)

# Confidence below this threshold → ask user to confirm the exercise data
LOW_CONFIDENCE_THRESHOLD = 0.5

# Canonical name map for common spoken variations
_CANONICAL_NAMES = {
    "bench": "barbell_bench_press",
    "bench press": "barbell_bench_press",
    "flat bench": "barbell_bench_press",
    "incline bench": "incline_barbell_bench_press",
    "incline": "incline_barbell_bench_press",
    "squat": "barbell_back_squat",
    "squats": "barbell_back_squat",
    "back squat": "barbell_back_squat",
    "deadlift": "conventional_deadlift",
    "deadlifts": "conventional_deadlift",
    "dl": "conventional_deadlift",
    "rdl": "romanian_deadlift",
    "romanian deadlift": "romanian_deadlift",
    "ohp": "overhead_press",
    "overhead press": "overhead_press",
    "shoulder press": "overhead_press",
    "military press": "overhead_press",
    "pull up": "pull_up",
    "pull ups": "pull_up",
    "pullup": "pull_up",
    "pullups": "pull_up",
    "chin up": "chin_up",
    "chin ups": "chin_up",
    "row": "barbell_row",
    "rows": "barbell_row",
    "barbell row": "barbell_row",
    "cable row": "seated_cable_row",
    "lat pulldown": "lat_pulldown",
    "dip": "tricep_dip",
    "dips": "tricep_dip",
    "curl": "barbell_curl",
    "curls": "barbell_curl",
    "bicep curl": "barbell_curl",
    "tricep extension": "tricep_extension",
    "leg press": "leg_press",
    "leg curl": "leg_curl",
    "leg extension": "leg_extension",
    "calf raise": "calf_raise",
    "hip thrust": "hip_thrust",
    "hip thrusts": "hip_thrust",
    "lunges": "lunge",
    "lunge": "lunge",
    "face pull": "face_pull",
    "face pulls": "face_pull",
    "lateral raise": "lateral_raise",
    "lateral raises": "lateral_raise",
    "front raise": "front_raise",
    "toes to bar": "toes_to_bar",
    "ttb": "toes_to_bar",
    "ab wheel": "ab_wheel_rollout",
    "plank": "plank",
    "run": "treadmill_run",
    "treadmill": "treadmill_run",
    "bike": "stationary_bike",
    "cycling": "stationary_bike",
    "elliptical": "elliptical",
}


def canonicalize(name: str) -> str:
    """Normalize a spoken exercise name to a canonical key for history lookups."""
    clean = name.lower().strip().rstrip("s")  # rough depluralize
    if clean in _CANONICAL_NAMES:
        return _CANONICAL_NAMES[clean]
    # Try original (pluralized) form
    original = name.lower().strip()
    return _CANONICAL_NAMES.get(original, original.replace(" ", "_"))


# ── Media download ────────────────────────────────────────────────────────────

def fetch_whatsapp_media(media_url: str) -> bytes:
    """
    Download a Twilio media attachment using HTTP Basic Auth.
    Twilio media URLs require authentication with the account SID + auth token.
    Returns raw bytes on success, raises on failure.
    """
    response = requests.get(
        media_url,
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        timeout=30,
    )
    response.raise_for_status()
    return response.content


# ── Transcript parsing ────────────────────────────────────────────────────────

def parse_session_transcript(transcript: str, user_id: Optional[str] = None) -> dict:
    """
    Extract structured training data from a raw Whisper transcript.

    Handles:
    - Noisy gym audio (trainer and user both speaking)
    - Weight in various formats ("two plates", "185", "225 pounds", "100 kilos")
    - Confidence scoring per exercise
    - Trainer cues and form corrections separated from exercise data

    Returns:
        {
            exercises: [{
                name: str,
                canonical_name: str,
                sets: [{reps, weight_kg, rpe, notes}],
                trainer_cues: str,
                form_notes: str,
                confidence: float,
            }],
            session_type: str,        # strength | cardio | mobility | mixed
            estimated_duration_min: int | None,
            trainer_feedback: str,    # overall session feedback from trainer
            overall_confidence: float,
            parse_notes: str,         # what was unclear or assumed
        }
    """
    if not transcript or not transcript.strip():
        return _empty_parse("Empty transcript")

    prompt = f"""Extract structured training data from this gym session audio transcript.

Transcript:
{transcript[:4000]}

Instructions:
- Extract every exercise mentioned with sets, reps, and weight
- Convert all weights to kg (1 lb = 0.453592 kg). If unit unclear, assume lbs for US gym context.
  "Two plates" = 100kg (45lb plates each side + bar). "225" alone = 225 lbs = ~102kg.
- Assign a confidence score (0.0–1.0) per exercise based on how clearly it was mentioned
- Separate trainer cues/instructions from performance data
- Extract form corrections or safety notes (e.g. "keep your back straight", "left hip dropping")
- If something is unclear, flag it in parse_notes rather than inventing data
- session_type: "strength" if lifting focus, "cardio" if running/cycling, "mobility" if stretching/yoga, "mixed" if combined
- estimated_duration_min: extract if mentioned, else null

Return ONLY valid JSON:
{{
  "exercises": [
    {{
      "name": "spoken name",
      "canonical_name": "normalized_snake_case_name",
      "sets": [
        {{
          "reps": number_or_null,
          "weight_kg": number_or_null,
          "rpe": number_or_null,
          "notes": "string_or_null"
        }}
      ],
      "trainer_cues": "string_or_null",
      "form_notes": "string_or_null",
      "confidence": 0.0_to_1.0
    }}
  ],
  "session_type": "strength",
  "estimated_duration_min": number_or_null,
  "trainer_feedback": "string_or_null",
  "overall_confidence": 0.0_to_1.0,
  "parse_notes": "what was unclear or assumed"
}}"""

    try:
        response = _anthropic.messages.create(
            model=settings.claude_model,
            max_tokens=1500,
            system="You are a training session data extractor. Return only valid JSON. Never explain or add prose outside the JSON.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        parsed = json.loads(raw)

        # Apply canonical name normalization for any exercises Claude didn't normalize
        for ex in parsed.get("exercises", []):
            if not ex.get("canonical_name") or ex["canonical_name"] == ex.get("name", ""):
                ex["canonical_name"] = canonicalize(ex.get("name", ""))

        return parsed

    except Exception as e:
        logger.error(f"Session parse error: {e}")
        return _empty_parse(f"Parse failed: {e}")


def _empty_parse(reason: str) -> dict:
    return {
        "exercises": [],
        "session_type": "unknown",
        "estimated_duration_min": None,
        "trainer_feedback": None,
        "overall_confidence": 0.0,
        "parse_notes": reason,
    }


# ── PR detection ──────────────────────────────────────────────────────────────

def detect_personal_records(user_id: str, exercises: list) -> list:
    """
    Compare each exercise's max weight against the user's history.
    Returns a list of PR dicts: [{exercise_name, canonical_name, new_weight_kg, previous_best_kg}]

    Only flags a PR if:
    - weight_kg is present and > 0
    - confidence >= 0.6 (don't flag uncertain lifts as PRs)
    - it exceeds the previous best for that canonical name
    """
    supabase = db.get_db()
    prs = []

    for ex in exercises:
        canonical = ex.get("canonical_name", "")
        if not canonical:
            continue

        # Find the max weight across all sets in this session
        session_max = max(
            (s.get("weight_kg") or 0 for s in ex.get("sets", [])),
            default=0,
        )
        if session_max <= 0:
            continue

        if ex.get("confidence", 1.0) < 0.6:
            continue

        # Look up previous best for this exercise
        result = (
            supabase.table("exercise_history")
            .select("weight_kg")
            .eq("user_id", user_id)
            .eq("exercise_canonical_name", canonical)
            .eq("is_personal_record", False)  # exclude PRs from comparison to avoid inflating
            .order("weight_kg", desc=True)
            .limit(1)
            .execute()
        )

        previous_best = result.data[0]["weight_kg"] if result.data else None

        if previous_best is None or session_max > previous_best:
            prs.append({
                "exercise_name": ex.get("name", canonical),
                "canonical_name": canonical,
                "new_weight_kg": session_max,
                "previous_best_kg": previous_best,
            })

    return prs


# ── Storage ───────────────────────────────────────────────────────────────────

def store_session(
    user_id: str,
    transcript: str,
    parsed: dict,
    prs: list,
    trainer_person_id: Optional[str] = None,
    session_date: Optional[date] = None,
) -> dict:
    """
    Write the training session to Supabase.
    Creates one training_sessions row and one exercise_history row per set per exercise.
    Also marks health_daily_summary.trained = True for today.
    Returns the created training session row.
    """
    supabase = db.get_db()
    today = session_date or date.today()

    pr_canonical_names = {p["canonical_name"] for p in prs}

    # Build personal_records JSONB
    personal_records_json = [
        {
            "exercise": p["exercise_name"],
            "new_weight_kg": p["new_weight_kg"],
            "previous_best_kg": p["previous_best_kg"],
        }
        for p in prs
    ]

    # Insert training session
    session_result = supabase.table("training_sessions").insert({
        "user_id": user_id,
        "trainer_person_id": trainer_person_id,
        "session_date": today.isoformat(),
        "session_type": parsed.get("session_type", "strength"),
        "duration_minutes": parsed.get("estimated_duration_min"),
        "audio_transcript": transcript[:10000],  # cap at 10k chars
        "exercises": json.dumps(parsed.get("exercises", [])),
        "trainer_feedback": json.dumps({"notes": parsed.get("trainer_feedback")}),
        "personal_records": json.dumps(personal_records_json),
    }).execute()

    session_row = session_result.data[0] if session_result.data else {}
    session_id = session_row.get("id")

    # Insert one row per set into exercise_history
    for ex in parsed.get("exercises", []):
        canonical = ex.get("canonical_name", "")
        is_pr_exercise = canonical in pr_canonical_names

        for i, s in enumerate(ex.get("sets", []), 1):
            weight = s.get("weight_kg")
            reps = s.get("reps")
            if weight is None and reps is None:
                continue  # skip empty sets

            # For PR sets: flag the specific set where the max was hit
            is_this_set_pr = (
                is_pr_exercise
                and weight is not None
                and weight == max(
                    (st.get("weight_kg") or 0 for st in ex.get("sets", [])),
                    default=0,
                )
            )

            prev_best = next(
                (p["previous_best_kg"] for p in prs if p["canonical_name"] == canonical),
                None,
            )

            supabase.table("exercise_history").insert({
                "user_id": user_id,
                "training_session_id": session_id,
                "exercise_name": ex.get("name", canonical),
                "exercise_canonical_name": canonical,
                "set_number": i,
                "reps": reps,
                "weight_kg": weight,
                "rpe": s.get("rpe"),
                "is_personal_record": is_this_set_pr,
                "previous_best_weight": prev_best,
                "notes": s.get("notes"),
            }).execute()

    # Mark today as a training day in health_daily_summary
    existing = (
        supabase.table("health_daily_summary")
        .select("id")
        .eq("user_id", user_id)
        .eq("summary_date", today.isoformat())
        .execute()
    )
    if existing.data:
        supabase.table("health_daily_summary").update({
            "trained": True,
            "training_session_id": session_id,
        }).eq("user_id", user_id).eq("summary_date", today.isoformat()).execute()
    else:
        supabase.table("health_daily_summary").insert({
            "user_id": user_id,
            "summary_date": today.isoformat(),
            "trained": True,
            "training_session_id": session_id,
        }).execute()

    return session_row


# ── Session summary ───────────────────────────────────────────────────────────

def generate_session_summary(
    parsed: dict,
    prs: list,
    user_name: str = "there",
) -> str:
    """
    Generate a post-session WhatsApp summary in Genie voice.

    Tone: like a training partner who was there and paid attention.
    - Lead with the PR if there is one
    - Call out main lifts with real numbers
    - Include trainer feedback if there was something specific
    - Brief — 3–5 lines maximum
    - No motivational language, no emoji unless it's a genuine PR
    """
    exercises = parsed.get("exercises", [])
    trainer_feedback = parsed.get("trainer_feedback", "")
    duration = parsed.get("estimated_duration_min")

    # If parse was very low confidence, be honest
    if parsed.get("overall_confidence", 1.0) < LOW_CONFIDENCE_THRESHOLD or not exercises:
        note = parsed.get("parse_notes", "")
        return (
            f"The audio was tough to make out — I caught some of it but not all. "
            f"Want to send another note with the main lifts and I'll log those properly?"
            + (f"\n\nWhat I could make out: {note}" if note else "")
        )

    prompt = f"""Write a post-training WhatsApp message for Personal Genie to send.

User name: {user_name}
Session data:
{json.dumps({"exercises": exercises, "trainer_feedback": trainer_feedback, "duration_min": duration}, indent=2)}

Personal records set today:
{json.dumps(prs, indent=2)}

Rules:
- 3–5 lines maximum
- Lead with the PR if there is one (e.g. "New PR on bench — 195lbs, up from 185.")
- If no PR, lead with the main lift of the session
- Include real numbers for the top 2–3 exercises (sets × reps @ weight)
- Include trainer feedback only if it was specific and actionable
- End with session duration if known
- No motivational language ("great job", "crushed it", "amazing")
- No emoji unless there is a genuine PR (then one 🎯 is fine)
- Sound like a person who was there taking notes, not a fitness app

Format example (adapt freely, don't copy):
New PR on bench today — 195lbs, up from 185. 🎯
Shoulder press: 4×8 at 55lbs.
[Trainer name] flagged left hip on squats — watch that next session.
45 minutes total."""

    try:
        response = _anthropic.messages.create(
            model=settings.claude_model,
            max_tokens=300,
            system="You are Personal Genie. Write exactly what the prompt asks. No extra prose.",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    except Exception as e:
        logger.error(f"Summary generation error: {e}")
        # Fallback: plain text summary from parsed data
        lines = []
        if prs:
            p = prs[0]
            prev = f", up from {p['previous_best_kg']:.0f}kg" if p.get("previous_best_kg") else ""
            lines.append(f"New PR: {p['exercise_name']} at {p['new_weight_kg']:.0f}kg{prev}.")
        for ex in exercises[:3]:
            sets = ex.get("sets", [])
            if sets:
                reps = sets[0].get("reps")
                weight = sets[0].get("weight_kg")
                if reps and weight:
                    lines.append(f"{ex['name'].title()}: {len(sets)}×{reps} at {weight:.0f}kg.")
        if duration:
            lines.append(f"{duration} minutes total.")
        return "\n".join(lines) if lines else "Session logged."


# ── Main entry point ──────────────────────────────────────────────────────────

def process_session_voice_note(
    user_id: str,
    phone: str,
    media_url: str,
    media_content_type: str = "audio/ogg",
    trainer_person_id: Optional[str] = None,
) -> str:
    """
    Full pipeline: download → transcribe → parse → detect PRs → store → summarize → send.

    Called by the consent webhook when a voice note arrives during an active session.
    Returns the summary string that was sent to the user.
    """
    from services.whatsapp import send_message

    user = db.get_user_by_id(user_id)
    user_name = user.get("name", "").split()[0] if user else "there"

    # 1. Download media from Twilio
    try:
        audio_bytes = fetch_whatsapp_media(media_url)
    except Exception as e:
        logger.error(f"Media download failed for user {user_id}: {e}")
        reply = "Couldn't download the voice note. Try sending it again."
        send_message(phone, reply, user_id=user_id)
        return reply

    if len(audio_bytes) < 1000:
        reply = "That audio was too short to process. Send a longer voice note."
        send_message(phone, reply, user_id=user_id)
        return reply

    # 2. Transcribe with Whisper
    ext = ".ogg" if "ogg" in media_content_type else ".m4a"
    transcript = transcribe_audio(audio_bytes, filename=f"session{ext}")

    if not transcript:
        reply = "Couldn't transcribe the audio — it might be too noisy. Try again or text me the main lifts."
        send_message(phone, reply, user_id=user_id)
        return reply

    logger.info(f"Session transcript for user {user_id}: {len(transcript)} chars")

    # 3. Parse exercises from transcript
    parsed = parse_session_transcript(transcript, user_id)

    # 4. Detect PRs
    prs = detect_personal_records(user_id, parsed.get("exercises", []))

    # 5. Store session + exercise history
    store_session(
        user_id=user_id,
        transcript=transcript,
        parsed=parsed,
        prs=prs,
        trainer_person_id=trainer_person_id,
    )

    # 6. Generate and send summary
    summary = generate_session_summary(parsed, prs, user_name)
    send_message(phone, summary, user_id=user_id)

    logger.info(f"Session processed for user {user_id}: {len(parsed.get('exercises', []))} exercises, {len(prs)} PRs")
    return summary
