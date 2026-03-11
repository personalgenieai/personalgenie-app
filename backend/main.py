"""
main.py — FastAPI entry point for Personal Genie backend.

Registers all routers and starts the scheduler for:
- 30-minute message batch processing
- 7pm evening digest
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from routers import auth, consent, messages, voice, invites, people, health, spotify, permissions, rules, push, billing, trainer, mac
from routers.ingestion import router as ingestion_router
from routers.analyze import router as analyze_router
from services.icalendar_processor import router as calendar_router
from services.maps_processor import maps_router
from config import get_settings
import database as db
from services.whatsapp import send_evening_digest
from services.intelligence import generate_evening_digest
import anthropic
from supabase import create_client
from policy_engine.engine import PolicyEngine
from policy_engine import guard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("genie")
settings = get_settings()

# Global Policy Engine singleton — initialized on startup, used everywhere
policy_engine: PolicyEngine = None

# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(title="Personal Genie", version="1.0.0")

# Allow requests from the iOS app and personalgenie.ai
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routers
app.include_router(auth.router)
app.include_router(consent.router)
app.include_router(messages.router)
app.include_router(voice.router)
app.include_router(invites.router)
app.include_router(people.router)
app.include_router(health.router)
app.include_router(spotify.router)
app.include_router(permissions.router)
app.include_router(rules.router)
app.include_router(push.router)
app.include_router(billing.router)
app.include_router(trainer.router)
app.include_router(ingestion_router)
app.include_router(calendar_router)
app.include_router(maps_router)
app.include_router(analyze_router)
app.include_router(mac.router)


@app.get("/health")
async def health():
    """Simple health check — confirms the backend is running."""
    return {"status": "awake", "message": "Personal Genie is running 🔮"}


@app.get("/")
async def landing():
    """Serve the landing page."""
    import os
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Personal Genie API"}


# ── Scheduler — background jobs ───────────────────────────────────────────────

scheduler = AsyncIOScheduler()


async def run_message_batch_for_all_users():
    """
    Every 30 minutes: process unread messages for all users.
    Gets unprocessed WhatsApp messages → Claude analysis → People Graph updates
    → emotional state inference → group chat profiles.
    """
    try:
        result = db.get_db().table("users").select("id").eq("whatsapp_consented", True).execute()
        users = result.data

        for user in users:
            user_id = user["id"]
            unprocessed = db.get_unprocessed_messages(user_id, limit=50)
            if not unprocessed:
                continue

            from services.intelligence import analyze_messages
            from services.emotional_state import infer_from_messages
            from services.group_chat import analyze_group_messages
            from services.signal_extractor import extract_signals_from_message
            import asyncio

            # 1. Relationship intelligence — update People Graph
            analyze_messages(user_id, unprocessed)

            # 2. Emotional state — infer user's current mood
            infer_from_messages(user_id, unprocessed)

            # 3. Group chat profiles — update group dynamics
            analyze_group_messages(user_id, unprocessed)

            # 4. Third-party signal extraction — mine mentions of people not in this chat
            user_row = db.get_user_by_id(user_id)
            user_name = user_row.get("name", "") if user_row else ""
            for msg in unprocessed:
                text = msg.get("body") or msg.get("text") or ""
                sender = msg.get("sender_name", user_name)
                if text and len(text) > 30:
                    try:
                        asyncio.create_task(
                            extract_signals_from_message(
                                source_user_id=user_id,
                                message_text=text,
                                participants=[user_name, sender],
                            )
                        )
                    except Exception:
                        pass

            db.mark_messages_processed([m["id"] for m in unprocessed])
            logger.info(f"Batch processed {len(unprocessed)} messages for user {user_id}")

    except Exception as e:
        logger.error(f"Message batch error: {e}")


async def _run_drift_detection():
    """
    Daily at 2am UTC: find relationships that have gone quiet.
    Creates a moment for the closest person the user hasn't connected with in 21+ days.
    Respects the policy engine — won't fire for deceased persons or during crisis.
    """
    try:
        from datetime import datetime, timezone, timedelta
        result = db.get_db().table("users").select("id, phone").execute()
        users = result.data
        cutoff = datetime.now(timezone.utc) - timedelta(days=21)

        for user in users:
            user_id = user["id"]
            phone = user.get("phone", "")
            if not phone:
                continue

            people = db.get_people_for_user(user_id)
            # Find the highest-closeness person who's gone quiet
            drifted = None
            for person in people:
                # Skip deceased
                if person.get("status") == "deceased":
                    continue
                last = person.get("last_meaningful_exchange")
                if not last:
                    continue
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if last_dt < cutoff:
                    drifted = person
                    break  # already sorted by closeness desc

            if drifted:
                name = drifted.get("name", "someone close to you")
                days_silent = (datetime.now(timezone.utc) - datetime.fromisoformat(
                    drifted["last_meaningful_exchange"].replace("Z", "+00:00")
                )).days
                # Don't create duplicate drift moments within 14 days
                supabase = db.get_db()
                recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
                existing = (
                    supabase.table("moments")
                    .select("id")
                    .eq("owner_user_id", user_id)
                    .eq("person_id", drifted["id"])
                    .eq("triggered_by", "drift_detection")
                    .gte("created_at", recent_cutoff)
                    .execute()
                )
                if not existing.data:
                    # Try to open a proactive Genie conversation first
                    from services.genie_conversations import start_conversation, should_initiate
                    started = False
                    if phone and should_initiate(user_id, drifted["id"]):
                        conv_id = start_conversation(user_id, drifted["id"], "drift_check", phone)
                        started = bool(conv_id)

                    # Fall back to a moment in the digest if no conversation was started
                    if not started:
                        db.create_moment(
                            user_id=user_id,
                            person_id=drifted["id"],
                            suggestion=f"It's been {days_silent} days since you and {name} last connected. "
                                       f"A message today — even just checking in — would mean more than you think.",
                            triggered_by="drift_detection",
                        )
                    logger.info(f"Drift handled for {name} ({days_silent}d) — user {user_id} — conversation={started}")

    except Exception as e:
        logger.error(f"Drift detection error: {e}")


async def _run_life_events_check():
    """
    Daily at 2am UTC: check every user for upcoming birthdays / anniversaries.
    Creates high-urgency moments for events in the next 3 days.
    These get delivered immediately via WhatsApp, not held for the digest.
    """
    try:
        from services.life_events import run_life_events_check_for_all_users
        from services.whatsapp import send_message

        result = db.get_db().table("users").select("id, phone, name").execute()
        users = result.data
        total_moments = run_life_events_check_for_all_users()

        # Send urgent moments immediately (don't wait for evening digest)
        from services.genie_conversations import start_conversation, should_initiate
        from routers.messages import set_last_moment
        for user in users:
            user_id = user["id"]
            phone = user.get("phone", "")
            if not phone:
                continue
            pending = db.get_moments_for_user(user_id)
            urgent = [m for m in pending if m.get("triggered_by") == "life_event"]
            for moment in urgent[:1]:  # max one urgent push per day
                suggestion = moment.get("suggestion", "")
                person_data = moment.get("people") or {}
                pname = person_data.get("name", "") if isinstance(person_data, dict) else ""
                person_id = moment.get("person_id")
                moment_id = moment.get("id")

                # For birthdays 1-2 days away, start a birthday_prep conversation
                # so Genie can help the user think of something meaningful to say
                started_conv = False
                if person_id and should_initiate(user_id, person_id):
                    conv_id = start_conversation(user_id, person_id, "birthday_prep", phone)
                    started_conv = bool(conv_id)

                # Fall back to sending the moment directly if conversation wasn't started
                if not started_conv:
                    send_message(phone, suggestion, user_id=user_id, moment_id=moment_id)
                    set_last_moment(user_id, pname, suggestion, "life_event")

                db.update_moment_status(moment_id, "sent")

        logger.info(f"Life events check done: {total_moments} moments created")
    except Exception as e:
        logger.error(f"Life events check error: {e}")


async def send_evening_digests():
    """
    Every evening at 7pm local (UTC-8 for SF): send each user their digest.
    One person. One insight. One suggestion. Nothing more.
    """
    try:
        result = db.get_db().table("users").select("id, phone, name").eq("whatsapp_consented", True).execute()
        users = result.data

        for user in users:
            user_id = user["id"]
            phone = user.get("phone", "")
            if not phone:
                continue

            from services.emotional_state import should_send_digest
            ok_to_send, reason = should_send_digest(user_id)
            if not ok_to_send:
                logger.info(f"Digest skipped for user {user_id}: {reason}")
                continue

            person_name, insight, suggestion, moment_id = generate_evening_digest(user_id)
            if person_name and insight:
                send_evening_digest(phone, person_name, insight, suggestion)
                if moment_id:
                    db.update_moment_status(moment_id, "sent")
                    # Tell the conversation agent what was just surfaced
                    moment_row = db.get_db().table("moments").select("triggered_by").eq("id", moment_id).execute()
                    triggered_by = moment_row.data[0]["triggered_by"] if moment_row.data else "google_ingestion"
                    from routers.messages import set_last_moment
                    set_last_moment(user_id, person_name, suggestion, triggered_by)
                logger.info(f"Sent digest to user {user_id}: {person_name} ({suggestion[:40]})")

    except Exception as e:
        logger.error(f"Evening digest error: {e}")


async def _run_health_nudge():
    """
    Daily at 8pm local (4am UTC): send a light nudge if no food has been logged today.
    One nudge per day maximum. Variant rotates so it never repeats two days running.
    Suppressed if a learning question was already sent today (don't double-ping).
    Only fires after the first day of logging (user has opted in by logging at least once).
    """
    from services.nutrition import get_daily_summary, get_days_logging
    from services.whatsapp import send_message
    from services.habit import (
        pick_nudge_variant,
        question_was_sent_today,
        get_last_nudge_variant_idx,
        record_nudge_variant,
    )

    NUDGE_VARIANTS = [
        "Haven't heard what you ate today.",
        "Still waiting on today's food. What did you have?",
        "No log yet today — what did lunch look like?",
        "Today's still a blank. Catch me up when you get a chance.",
    ]

    try:
        result = db.get_db().table("users").select("id, phone").eq("whatsapp_consented", True).execute()
        users = result.data

        for user in users:
            user_id = user["id"]
            phone = user.get("phone", "")
            if not phone:
                continue

            days = get_days_logging(user_id)
            if days == 0:
                continue  # Never used health logging — don't nudge

            daily = get_daily_summary(user_id)
            already_nudged = daily.get("nudge_sent", False)
            has_logged_today = (daily.get("total_calories", 0) or 0) > 0

            if has_logged_today or already_nudged:
                continue

            # Don't nudge if a learning question was already sent today
            if question_was_sent_today(user_id):
                logger.info(f"Nudge suppressed for {user_id} — learning question already sent today")
                continue

            last_idx = get_last_nudge_variant_idx(user_id)
            variant_idx, nudge = pick_nudge_variant(NUDGE_VARIANTS, last_idx)
            send_message(phone, nudge, user_id=user_id)
            record_nudge_variant(user_id, variant_idx)

            # Mark nudge as sent so we don't fire twice
            if daily.get("id"):
                db.get_db().table("health_daily_summary").update(
                    {"nudge_sent": True}
                ).eq("id", daily["id"]).execute()
            else:
                from datetime import date
                db.get_db().table("health_daily_summary").insert({
                    "user_id": user_id,
                    "summary_date": date.today().isoformat(),
                    "nudge_sent": True,
                }).execute()

            logger.info(f"Health nudge sent to user {user_id} (variant {variant_idx})")

    except Exception as e:
        logger.error(f"Health nudge error: {e}")


async def _run_weekly_rollup():
    """
    Every Sunday at 9am SF (5pm UTC): send each user a plain summary of
    the week's food and training numbers. No analysis — just the facts.
    Skipped if fewer than 2 days were logged (nothing useful to say).
    """
    from services.habit import get_weekly_summary, build_weekly_rollup_message
    from services.whatsapp import send_message

    try:
        result = db.get_db().table("users").select("id, phone, name").eq("whatsapp_consented", True).execute()
        users = result.data

        for user in users:
            user_id = user["id"]
            phone = user.get("phone", "")
            if not phone:
                continue

            summary = get_weekly_summary(user_id)
            message = build_weekly_rollup_message(summary)
            if message:
                send_message(phone, message, user_id=user_id)
                logger.info(f"Weekly roll-up sent to user {user_id}: {summary['days_logged']} days logged")

    except Exception as e:
        logger.error(f"Weekly roll-up error: {e}")


@app.get("/policy-dashboard")
async def policy_dashboard():
    """
    Returns the current status of the Policy Engine — which policies are
    loaded, compiled, and their last test results.
    """
    if policy_engine is None:
        return {"status": "not_initialized", "policies": []}
    return policy_engine.get_policy_status()


@app.get("/policy-audit/{user_id}")
async def policy_audit(user_id: str, days: int = 30):
    """Return the policy decision audit log for a specific user (Transparency tab)."""
    if policy_engine is None:
        return {"decisions": []}
    return {"decisions": policy_engine.get_audit_log(user_id, days=days)}


@app.post("/policy-reload")
async def policy_reload():
    """Hot-reload all policies from the database without restarting. Admin use only."""
    if policy_engine is None:
        return {"status": "not_initialized"}
    policy_engine.reload_policies()
    return {"status": "reloaded", "compiled": len(policy_engine.compiled_policies)}


async def rule_engine_job():
    """Every 15 minutes: evaluate all active genie_rules for all users."""
    try:
        from services.rule_engine import RuleEngine
        engine = RuleEngine()
        result = await engine.evaluate_all_users()
        logger.info(f"Rule engine: {result}")
    except Exception as e:
        logger.error(f"Rule engine job error: {e}")


async def capability_lifecycle_job():
    """Daily at 6am UTC: evaluate capability lifecycle for all users."""
    try:
        from services.capability_lifecycle import CapabilityLifecycleEngine
        engine = CapabilityLifecycleEngine()
        result = await engine.evaluate_all_users()
        logger.info(f"Capability lifecycle: {result}")
    except Exception as e:
        logger.error(f"Capability lifecycle job error: {e}")


async def nightly_conversations_job():
    """Daily at 5am UTC (9pm PT): send nightly conversations."""
    try:
        from services.nightly_conversations import NightlyConversationEngine
        engine = NightlyConversationEngine()
        result = await engine.run_for_all_users()
        logger.info(f"Nightly conversations: {result}")
    except Exception as e:
        logger.error(f"Nightly conversations job error: {e}")


@app.on_event("startup")
async def startup():
    """Start background jobs and initialize Policy Engine when the server starts."""
    global policy_engine

    # Initialize the Policy Engine — loads and compiles all policies from DB
    try:
        supabase_client = create_client(settings.supabase_url, settings.supabase_key)
        claude_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        policy_engine = PolicyEngine(supabase=supabase_client, claude=claude_client)
        guard.init(policy_engine)
        logger.info(f"Policy Engine initialized: {len(policy_engine.compiled_policies)} policies compiled")
    except Exception as e:
        logger.error(f"Policy Engine failed to initialize: {e} — all operations will be permitted")

    # Process messages every 30 minutes
    scheduler.add_job(
        run_message_batch_for_all_users,
        trigger=IntervalTrigger(minutes=30),
        id="message_batch",
        replace_existing=True,
    )

    # Send evening digest at 7pm SF time (UTC+0 = 3am, UTC-8 = 7pm, use UTC 3:00)
    scheduler.add_job(
        send_evening_digests,
        trigger=CronTrigger(hour=3, minute=0),  # 7pm SF = 3am UTC
        id="evening_digest",
        replace_existing=True,
    )

    # Check upcoming birthdays and anniversaries at 2am UTC (6pm PT)
    scheduler.add_job(
        _run_life_events_check,
        trigger=CronTrigger(hour=2, minute=0),
        id="life_events_check",
        replace_existing=True,
    )

    # Drift detection at 2am UTC — surface quieted relationships
    scheduler.add_job(
        _run_drift_detection,
        trigger=CronTrigger(hour=2, minute=15),
        id="drift_detection",
        replace_existing=True,
    )

    # Health habit nudge at 8pm SF time (4am UTC) — send if no food logged today
    scheduler.add_job(
        _run_health_nudge,
        trigger=CronTrigger(hour=4, minute=0),   # 8pm SF = 4am UTC
        id="health_nudge",
        replace_existing=True,
    )

    # Weekly roll-up every Sunday at 9am SF (5pm UTC)
    scheduler.add_job(
        _run_weekly_rollup,
        trigger=CronTrigger(day_of_week="sun", hour=17, minute=0),  # 9am SF = 5pm UTC
        id="weekly_rollup",
        replace_existing=True,
    )

    # Rule Engine — evaluate user-defined rules every 15 minutes
    scheduler.add_job(
        rule_engine_job,
        trigger=IntervalTrigger(minutes=15),
        id="rule_engine",
        replace_existing=True,
    )

    # Capability Lifecycle — evaluate capability areas daily at 6am UTC
    scheduler.add_job(
        capability_lifecycle_job,
        trigger=CronTrigger(hour=6, minute=0),
        id="capability_lifecycle",
        replace_existing=True,
    )

    # Nightly conversations — 5am UTC = 9pm PT
    scheduler.add_job(
        nightly_conversations_job,
        trigger=CronTrigger(hour=5, minute=0),
        id="nightly_conversations",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Personal Genie backend started 🔮")


@app.on_event("shutdown")
async def shutdown():
    """Stop background jobs cleanly."""
    scheduler.shutdown()
