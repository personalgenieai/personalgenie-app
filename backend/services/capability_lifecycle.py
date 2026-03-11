"""
services/capability_lifecycle.py — Capability Lifecycle Engine.

Tracks 8 capability areas through 6 stages (0=unaware → 5=ambient).
Evaluates daily at 6am UTC. Advances stages when signal + trust thresholds are met.
Sends warm WhatsApp offers when a capability reaches stage 3.

Capability areas: physical, financial, communication, coordination,
                  intellectual, family, emotional, professional

Music special rule: auto-advance to stage 5 as soon as Spotify/Apple Music connected.
"""
import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import database as db
from services.intelligence import _call_claude

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

CAPABILITY_AREAS = [
    "physical", "financial", "communication", "coordination",
    "intellectual", "family", "emotional", "professional",
]

# Stage definitions
STAGE_UNAWARE = 0
STAGE_OBSERVING = 1
STAGE_READY = 2
STAGE_OFFERED = 3
STAGE_ACTIVE_LEARNING = 4
STAGE_AMBIENT = 5

# Thresholds from PRD
SIGNAL_THRESHOLD = 0.70
TRUST_THRESHOLD = 0.60
MIN_DAYS = 14
MIN_INTERACTIONS = 20
MAX_OFFERS_PER_MONTH = 1
DECLINE_COOLDOWN_DAYS = 90

# Warm offer messages per capability area
OFFER_MESSAGES = {
    "physical": (
        "I've noticed you care about how you fuel yourself. "
        "I could track your nutrition patterns over time — weekly summaries, training context, the whole picture. "
        "Want me to pay more attention to this?"
    ),
    "financial": (
        "Money comes up in your life in ways that seem worth tracking — not judging, just noticing. "
        "I could start keeping a quiet eye on spending patterns and flag things worth knowing. "
        "Would that be useful?"
    ),
    "communication": (
        "You're in a lot of conversations that matter. "
        "I could start tracking the rhythms — who you're in touch with, who's gone quiet, what's worth a reply. "
        "Want me to pay closer attention to this?"
    ),
    "coordination": (
        "You've got a lot moving at once. "
        "I could start helping coordinate the logistics — calendar overlap, timing, who needs what when. "
        "Should I start watching for that?"
    ),
    "intellectual": (
        "You think about interesting things. "
        "I could start tracking the ideas and questions that keep coming up for you — and occasionally connect the dots. "
        "Want me to pay more attention to what's catching your mind?"
    ),
    "family": (
        "Family shows up a lot in your world. "
        "I could start tracking the moments that matter there — birthdays, rhythms, who might need a call. "
        "Should I start paying closer attention?"
    ),
    "emotional": (
        "I've picked up on some things about how you're doing, not just what you're doing. "
        "I could be more intentional about checking in — gently, without making it a thing. "
        "Is that something you'd want?"
    ),
    "professional": (
        "Your work and side projects come up here and there. "
        "I could start tracking what's in motion professionally — without going near anything confidential. "
        "Want me to keep a quiet eye on that?"
    ),
}


class CapabilityLifecycleEngine:
    """
    Evaluates capability areas for each user and advances stages
    when signal and trust thresholds are met.
    """

    async def evaluate_all_users(self) -> dict:
        """
        Run lifecycle evaluation for all consented users.
        Returns summary: {users_evaluated, areas_advanced, offers_sent}
        """
        users_evaluated = 0
        total_advanced = 0
        total_offers = 0

        try:
            result = db.get_db().table("users").select("id, phone, created_at").eq("whatsapp_consented", True).execute()
            users = result.data or []
        except Exception as e:
            logger.error(f"CapabilityLifecycle: could not load users: {e}")
            return {"users_evaluated": 0, "areas_advanced": 0, "offers_sent": 0}

        for user in users:
            user_id = user.get("id")
            phone = user.get("phone", "")
            if not user_id or not phone:
                continue
            users_evaluated += 1
            try:
                advanced = await self.evaluate_for_user(user_id, phone)
                total_advanced += len(advanced)
            except Exception as e:
                logger.error(f"CapabilityLifecycle: error for user {user_id}: {e}")

        logger.info(
            f"CapabilityLifecycle: evaluated {users_evaluated} users, "
            f"{total_advanced} areas advanced"
        )
        return {"users_evaluated": users_evaluated, "areas_advanced": total_advanced, "offers_sent": total_offers}

    async def evaluate_for_user(self, user_id: str, phone: str) -> list:
        """
        Evaluate all 8 capability areas for a single user.
        Returns list of area names that were advanced.
        """
        advanced = []

        # Check music auto-stage first
        await self._auto_stage_music(user_id, phone)

        trust_score = await self._get_trust_score(user_id)
        user_row = db.get_user_by_id(user_id)
        if not user_row:
            return advanced

        created_at_str = user_row.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            days_since_signup = (datetime.now(timezone.utc) - created_at).days
        except Exception:
            days_since_signup = 0

        # Check minimum days requirement
        if days_since_signup < MIN_DAYS:
            return advanced

        # Check minimum interactions
        total_interactions = self._get_interaction_count(user_id)
        if total_interactions < MIN_INTERACTIONS:
            return advanced

        supabase = db.get_db()

        for area in CAPABILITY_AREAS:
            if area == "coordination":
                # Not enough signal infrastructure yet — skip
                continue

            try:
                # Load current state
                row = self._get_lifecycle_row(user_id, area)
                current_stage = row.get("stage", STAGE_UNAWARE)

                # Don't re-evaluate areas already in active or ambient stage
                if current_stage >= STAGE_ACTIVE_LEARNING:
                    continue

                # Music is handled separately
                if area == "physical":
                    # Check if music area — skip, handled by _auto_stage_music
                    pass

                signal_score = await self._compute_signal_score(area, user_id)

                # Update signal score regardless of transitions
                self._upsert_lifecycle(user_id, area, {
                    "signal_score": signal_score,
                    "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
                })

                new_stage = current_stage

                # Stage transitions
                if current_stage == STAGE_UNAWARE and signal_score > 0:
                    new_stage = STAGE_OBSERVING

                elif current_stage == STAGE_OBSERVING:
                    if signal_score >= SIGNAL_THRESHOLD and trust_score >= TRUST_THRESHOLD:
                        new_stage = STAGE_READY

                elif current_stage == STAGE_READY:
                    # Check offer cooldown before sending
                    if not self._offer_on_cooldown(user_id, area):
                        # Check decline cooldown
                        declined_at = row.get("declined_at")
                        if declined_at:
                            declined_dt = datetime.fromisoformat(declined_at.replace("Z", "+00:00"))
                            if (datetime.now(timezone.utc) - declined_dt).days < DECLINE_COOLDOWN_DAYS:
                                continue

                        # Advance to offered and send offer
                        new_stage = STAGE_OFFERED
                        self._upsert_lifecycle(user_id, area, {
                            "stage": new_stage,
                            "offered_at": datetime.now(timezone.utc).isoformat(),
                        })
                        await self._send_capability_offer(area, user_id, phone)
                        advanced.append(area)
                        continue

                if new_stage != current_stage:
                    self._upsert_lifecycle(user_id, area, {"stage": new_stage})
                    if new_stage > current_stage:
                        advanced.append(area)
                        logger.info(f"CapabilityLifecycle: {area} advanced {current_stage}→{new_stage} for user {user_id}")

            except Exception as e:
                logger.error(f"CapabilityLifecycle: error evaluating {area} for user {user_id}: {e}")

        return advanced

    async def _compute_signal_score(self, area: str, user_id: str) -> float:
        """
        Compute signal score (0.0–1.0) for a capability area based on available data.
        Each signal source adds to the running total, capped at 1.0.
        """
        score = 0.0

        try:
            if area == "physical":
                score = await self._score_physical(user_id)
            elif area == "financial":
                score = await self._score_financial(user_id)
            elif area == "communication":
                score = await self._score_communication(user_id)
            elif area == "intellectual":
                score = await self._score_intellectual(user_id)
            elif area == "family":
                score = await self._score_family(user_id)
            elif area == "emotional":
                score = await self._score_emotional(user_id)
            elif area == "professional":
                score = 0.0  # Mostly blocked by WorkFilter
            elif area == "coordination":
                score = 0.0  # Not enough infrastructure yet
        except Exception as e:
            logger.warning(f"CapabilityLifecycle: signal score failed for {area}/{user_id}: {e}")

        return min(score, 1.0)

    async def _score_physical(self, user_id: str) -> float:
        """Physical: food logs, training sessions, health questions, summary rows."""
        score = 0.0
        supabase = db.get_db()

        # food_logs_this_week > 3: +0.3
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        food_logs = (
            supabase.table("health_daily_summary")
            .select("summary_date")
            .eq("user_id", user_id)
            .gte("summary_date", week_ago)
            .gt("total_calories", 0)
            .execute()
        )
        if len(food_logs.data or []) > 3:
            score += 0.3

        # training_sessions_this_week > 1: +0.2
        training = (
            supabase.table("training_sessions")
            .select("id")
            .eq("user_id", user_id)
            .gte("session_date", week_ago)
            .execute()
        )
        if len(training.data or []) > 1:
            score += 0.2

        # health_daily_summary rows > 7: +0.2
        all_rows = (
            supabase.table("health_daily_summary")
            .select("summary_date")
            .eq("user_id", user_id)
            .gt("total_calories", 0)
            .execute()
        )
        if len(all_rows.data or []) > 7:
            score += 0.2

        # Health questions answered (from messages): +0.1 each max +0.3
        health_keywords = ["calories", "protein", "nutrition", "workout", "training", "gym", "health"]
        try:
            msgs = (
                supabase.table("messages")
                .select("body")
                .eq("owner_user_id", user_id)
                .eq("processed", True)
                .limit(100)
                .execute()
            )
            health_msg_count = sum(
                1 for m in (msgs.data or [])
                if any(kw in (m.get("body") or "").lower() for kw in health_keywords)
            )
            score += min(0.3, health_msg_count * 0.1)
        except Exception:
            pass

        return score

    async def _score_financial(self, user_id: str) -> float:
        """Financial: messages mentioning money keywords + third_party_signals."""
        score = 0.0
        supabase = db.get_db()

        fin_keywords = ["money", "budget", "spending", "rent", "bills", "cost", "price", "pay", "invest"]
        try:
            msgs = (
                supabase.table("messages")
                .select("body")
                .eq("owner_user_id", user_id)
                .eq("processed", True)
                .limit(200)
                .execute()
            )
            fin_count = sum(
                1 for m in (msgs.data or [])
                if any(kw in (m.get("body") or "").lower() for kw in fin_keywords)
            )
            score += min(0.6, fin_count * 0.2)
        except Exception:
            pass

        # Third-party financial signals: +0.2
        try:
            signals = (
                supabase.table("third_party_signals")
                .select("signal_type")
                .eq("subject_user_id", user_id)
                .execute()
            )
            fin_signals = [s for s in (signals.data or []) if "financial" in (s.get("signal_type") or "")]
            if fin_signals:
                score += 0.2
        except Exception:
            pass

        return score

    async def _score_communication(self, user_id: str) -> float:
        """Communication: message count, people graph size, bilateral connections."""
        score = 0.0
        supabase = db.get_db()

        # messages_processed_count > 20: +0.3
        try:
            msgs = (
                supabase.table("messages")
                .select("id")
                .eq("owner_user_id", user_id)
                .eq("processed", True)
                .execute()
            )
            if len(msgs.data or []) > 20:
                score += 0.3
        except Exception:
            pass

        # people graph size > 5: +0.2
        try:
            people = db.get_people_for_user(user_id)
            if len(people) > 5:
                score += 0.2
        except Exception:
            pass

        # bilateral connections > 0: +0.3
        try:
            bilateral = (
                supabase.table("people")
                .select("id")
                .eq("owner_user_id", user_id)
                .eq("bilateral", True)
                .execute()
            )
            if bilateral.data:
                score += 0.3
        except Exception:
            pass

        return score

    async def _score_intellectual(self, user_id: str) -> float:
        """Intellectual: messages mentioning books/ideas + interest signals."""
        score = 0.0
        supabase = db.get_db()

        intellectual_keywords = ["book", "article", "idea", "learning", "read", "thought", "concept", "theory"]
        try:
            msgs = (
                supabase.table("messages")
                .select("body")
                .eq("owner_user_id", user_id)
                .eq("processed", True)
                .limit(200)
                .execute()
            )
            intel_count = sum(
                1 for m in (msgs.data or [])
                if any(kw in (m.get("body") or "").lower() for kw in intellectual_keywords)
            )
            score += min(0.6, intel_count * 0.15)
        except Exception:
            pass

        # Interest signals with category "intellectual": +0.2
        try:
            interests = (
                supabase.table("interest_signals")
                .select("category")
                .eq("user_id", user_id)
                .eq("category", "intellectual")
                .execute()
            )
            if interests.data:
                score += 0.2
        except Exception:
            pass

        return score

    async def _score_family(self, user_id: str) -> float:
        """Family: people with family relationship types + calendar events with family keywords."""
        score = 0.0
        supabase = db.get_db()

        family_keywords = ["family", "mom", "dad", "sister", "brother", "mother", "father", "parent",
                           "son", "daughter", "grandma", "grandpa", "uncle", "aunt", "cousin"]

        # People with family relationships: +0.2 each, max 0.6
        try:
            people = db.get_people_for_user(user_id)
            family_count = sum(
                1 for p in people
                if any(kw in (p.get("relationship_type") or "").lower() for kw in family_keywords)
            )
            score += min(0.6, family_count * 0.2)
        except Exception:
            pass

        # Calendar events with family keywords: +0.2
        try:
            events = (
                supabase.table("calendar_events")
                .select("title")
                .eq("user_id", user_id)
                .execute()
            )
            family_events = [
                e for e in (events.data or [])
                if any(kw in (e.get("title") or "").lower() for kw in family_keywords)
            ]
            if family_events:
                score += 0.2
        except Exception:
            pass

        return score

    async def _score_emotional(self, user_id: str) -> float:
        """Emotional: genie_conversations count, third_party_signals, emotional state changes."""
        score = 0.0
        supabase = db.get_db()

        # genie_conversations count > 2: +0.2
        try:
            convs = (
                supabase.table("genie_conversations")
                .select("id")
                .eq("owner_user_id", user_id)
                .execute()
            )
            if len(convs.data or []) > 2:
                score += 0.2
        except Exception:
            pass

        # third_party_signals about this user > 1: +0.3
        try:
            signals = (
                supabase.table("third_party_signals")
                .select("id")
                .eq("subject_user_id", user_id)
                .execute()
            )
            if len(signals.data or []) > 1:
                score += 0.3
        except Exception:
            pass

        # Emotional state changes tracked > 3: +0.2
        try:
            states = (
                supabase.table("emotional_states")
                .select("id")
                .eq("owner_user_id", user_id)
                .execute()
            )
            if len(states.data or []) > 3:
                score += 0.2
        except Exception:
            pass

        return score

    async def _get_trust_score(self, user_id: str) -> float:
        """
        Trust score = days_since_signup / 90, capped at 1.0.
        Measures how long the user has been on the platform.
        """
        try:
            user_row = db.get_user_by_id(user_id)
            if not user_row:
                return 0.0
            created_at_str = user_row.get("created_at", "")
            if not created_at_str:
                return 0.0
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - created_at).days
            return min(1.0, days / 90.0)
        except Exception as e:
            logger.warning(f"CapabilityLifecycle: trust score failed for {user_id}: {e}")
            return 0.0

    async def _send_capability_offer(self, area: str, user_id: str, phone: str) -> None:
        """Send the capability offer WhatsApp message for a given area."""
        from services.whatsapp import send_message
        message = OFFER_MESSAGES.get(area)
        if not message:
            logger.warning(f"CapabilityLifecycle: no offer message defined for area '{area}'")
            return
        try:
            send_message(phone, message, user_id=user_id)
            logger.info(f"CapabilityLifecycle: offer sent for {area} to user {user_id}")
        except Exception as e:
            logger.error(f"CapabilityLifecycle: could not send offer for {area} to user {user_id}: {e}")

    async def _auto_stage_music(self, user_id: str, phone: str) -> None:
        """
        Music special rule: auto-advance to stage 5 as soon as
        Spotify or Apple Music is connected.
        """
        try:
            supabase = db.get_db()
            result = (
                supabase.table("music_connections")
                .select("provider")
                .eq("user_id", user_id)
                .execute()
            )
            if not result.data:
                return  # No music connection

            # Check if already at stage 5
            row = self._get_lifecycle_row(user_id, "music")
            if row.get("stage", 0) >= STAGE_AMBIENT:
                return

            # Advance to ambient
            self._upsert_lifecycle(user_id, "music", {
                "stage": STAGE_AMBIENT,
                "signal_score": 1.0,
                "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
                "accepted_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(f"CapabilityLifecycle: music auto-advanced to stage 5 for user {user_id}")
        except Exception as e:
            logger.warning(f"CapabilityLifecycle: music auto-stage failed for {user_id}: {e}")

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _get_lifecycle_row(self, user_id: str, area: str) -> dict:
        """Load the lifecycle row for a user+area, or return empty dict."""
        try:
            result = (
                db.get_db()
                .table("capability_lifecycle")
                .select("*")
                .eq("user_id", user_id)
                .eq("area", area)
                .execute()
            )
            return result.data[0] if result.data else {}
        except Exception:
            return {}

    def _upsert_lifecycle(self, user_id: str, area: str, updates: dict) -> None:
        """Upsert a capability_lifecycle record with the provided field updates."""
        try:
            existing = self._get_lifecycle_row(user_id, area)
            if existing.get("user_id"):
                # Update
                db.get_db().table("capability_lifecycle").update(updates).eq("user_id", user_id).eq("area", area).execute()
            else:
                # Insert with defaults
                payload = {
                    "user_id": user_id,
                    "area": area,
                    "stage": STAGE_UNAWARE,
                    "signal_score": 0.0,
                    **updates,
                }
                db.get_db().table("capability_lifecycle").insert(payload).execute()
        except Exception as e:
            logger.error(f"CapabilityLifecycle: upsert failed for {user_id}/{area}: {e}")

    def _offer_on_cooldown(self, user_id: str, area: str) -> bool:
        """
        Check if we've already sent an offer for this area within the last month.
        Enforces max_offers_per_month = 1.
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            result = (
                db.get_db()
                .table("capability_lifecycle")
                .select("offered_at")
                .eq("user_id", user_id)
                .eq("area", area)
                .gte("offered_at", cutoff)
                .execute()
            )
            return bool(result.data)
        except Exception:
            return False

    def _get_interaction_count(self, user_id: str) -> int:
        """Count total processed messages as a proxy for interaction count."""
        try:
            result = (
                db.get_db()
                .table("messages")
                .select("id")
                .eq("owner_user_id", user_id)
                .eq("processed", True)
                .execute()
            )
            return len(result.data or [])
        except Exception:
            return 0
