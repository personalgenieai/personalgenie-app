"""
services/nightly_conversations.py — Nightly Conversation Engine.

Once per evening (9pm user local / 5am UTC), Genie initiates a thoughtful open-ended
conversation — not about a task, not pushing a moment. Just deepening the relationship.

This is different from:
  - Morning digest (inform, not converse)
  - genie_conversations.py (relationship-specific, about another person)

This is Genie checking in on the user themselves.

Topic priority:
  1. Third-party signal about this user
  2. Relationship pattern change
  3. Health pattern
  4. Something the user mentioned emotionally
  5. Open reflection fallback

Tracked in nightly_conversations table:
  user_id, seed_type, opening_message, sent_at, user_replied, reply_count
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import database as db
from services.intelligence import _call_claude

logger = logging.getLogger(__name__)

# Minimum hours between nightly conversations
MIN_HOURS_BETWEEN = 72  # 3 days

# Seeds in priority order
SEED_PRIORITY = [
    "third_party_signal",
    "relationship_pattern",
    "health_pattern",
    "user_mention",
    "open_reflection",
]

# Notification preferences that allow nightly messages
ALLOWED_PREFERENCES = ("evenings", "when_it_matters", None)  # None = default allowed


class NightlyConversationEngine:
    """
    Initiates one warm, open-ended nightly conversation per user.
    Uses World Model context to pick the most resonant topic seed.
    """

    async def run_for_all_users(self) -> dict:
        """
        Run nightly conversation engine for all eligible users.
        Returns: {users_checked, conversations_sent, skipped}
        """
        users_checked = 0
        conversations_sent = 0
        skipped = 0

        try:
            result = db.get_db().table("users").select("id, phone").eq("whatsapp_consented", True).execute()
            users = result.data or []
        except Exception as e:
            logger.error(f"NightlyConversations: could not load users: {e}")
            return {"users_checked": 0, "conversations_sent": 0, "skipped": 0}

        for user in users:
            user_id = user.get("id")
            phone = user.get("phone", "")
            if not user_id or not phone:
                continue
            users_checked += 1
            try:
                sent = await self.run_for_user(user_id, phone)
                if sent:
                    conversations_sent += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error(f"NightlyConversations: error for user {user_id}: {e}")
                skipped += 1

        logger.info(
            f"NightlyConversations: checked {users_checked} users, "
            f"sent {conversations_sent}, skipped {skipped}"
        )
        return {"users_checked": users_checked, "conversations_sent": conversations_sent, "skipped": skipped}

    async def run_for_user(self, user_id: str, phone: str) -> bool:
        """
        Run nightly conversation for a single user.
        Returns True if a conversation was sent.
        """
        # Check all conditions
        should = await self._should_send(user_id)
        if not should:
            return False

        # Pick the best seed
        seed = await self._select_seed(user_id)
        if not seed:
            return False

        # Generate the opening message
        opening = await self._generate_opening(user_id, seed)
        if not opening:
            return False

        # Send and record
        try:
            from services.whatsapp import send_message
            send_message(phone, opening, user_id=user_id)
        except Exception as e:
            logger.error(f"NightlyConversations: could not send message to {user_id}: {e}")
            return False

        # Record in nightly_conversations table
        try:
            db.get_db().table("nightly_conversations").insert({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "seed_type": seed.get("type", "open_reflection"),
                "opening_message": opening,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "user_replied": False,
                "reply_count": 0,
            }).execute()
        except Exception as e:
            logger.warning(f"NightlyConversations: could not record conversation for {user_id}: {e}")

        logger.info(f"NightlyConversations: sent to user {user_id} (seed: {seed.get('type')})")
        return True

    async def _should_send(self, user_id: str) -> bool:
        """
        Check all conditions for sending a nightly conversation.
        Returns True only if all conditions pass.
        """
        supabase = db.get_db()

        # 1. User has been active in last 7 days (has processed messages)
        try:
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            msgs = (
                supabase.table("messages")
                .select("id")
                .eq("owner_user_id", user_id)
                .eq("processed", True)
                .gte("created_at", week_ago)
                .limit(1)
                .execute()
            )
            if not msgs.data:
                return False
        except Exception as e:
            logger.warning(f"NightlyConversations: activity check failed for {user_id}: {e}")
            return False

        # 2. No nightly conversation sent in last 3 days
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=MIN_HOURS_BETWEEN)).isoformat()
            recent = (
                supabase.table("nightly_conversations")
                .select("id")
                .eq("user_id", user_id)
                .gte("sent_at", cutoff)
                .limit(1)
                .execute()
            )
            if recent.data:
                return False
        except Exception as e:
            logger.warning(f"NightlyConversations: recency check failed for {user_id}: {e}")
            return False

        # 3. Evening digest was NOT sent in the last 2 hours
        try:
            two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            digest_sent = (
                supabase.table("notifications")
                .select("id")
                .eq("owner_user_id", user_id)
                .eq("channel", "whatsapp")
                .gte("sent_at", two_hours_ago)
                .limit(1)
                .execute()
            )
            if digest_sent.data:
                return False
        except Exception as e:
            # Non-blocking — if we can't check, allow it
            logger.warning(f"NightlyConversations: digest check failed for {user_id}: {e}")

        # 4. Check notification preference
        try:
            user_row = db.get_user_by_id(user_id)
            pref = user_row.get("notification_preference") if user_row else None
            if pref and pref not in ("evenings", "when_it_matters"):
                return False
        except Exception as e:
            logger.warning(f"NightlyConversations: pref check failed for {user_id}: {e}")

        return True

    async def _select_seed(self, user_id: str) -> Optional[dict]:
        """
        Select the best seed topic from World Model context.
        Returns {type, context} dict, or None if no suitable seed found.
        """
        supabase = db.get_db()

        # Priority 1: Third-party signal about this user
        try:
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            signals = (
                supabase.table("third_party_signals")
                .select("*")
                .eq("subject_user_id", user_id)
                .gte("created_at", week_ago)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if signals.data:
                sig = signals.data[0]
                return {
                    "type": "third_party_signal",
                    "context": {
                        "signal_type": sig.get("signal_type", ""),
                        "raw_signal": sig.get("raw_signal", ""),
                    },
                }
        except Exception:
            pass

        # Priority 2: Relationship pattern — closeness score change or key person gone quiet
        try:
            people = db.get_people_for_user(user_id)
            if people:
                top_person = people[0]
                last_exchange = top_person.get("last_meaningful_exchange")
                if last_exchange:
                    last_dt = datetime.fromisoformat(last_exchange.replace("Z", "+00:00"))
                    days_silent = (datetime.now(timezone.utc) - last_dt).days
                    if days_silent >= 14:
                        return {
                            "type": "relationship_pattern",
                            "context": {
                                "person_name": top_person.get("name", "someone close"),
                                "days_silent": days_silent,
                                "relationship_type": top_person.get("relationship_type", ""),
                            },
                        }
        except Exception:
            pass

        # Priority 3: Health pattern — 3+ days logging with clear pattern
        try:
            week_ago_date = (date.today() - timedelta(days=7)).isoformat()
            health_rows = (
                supabase.table("health_daily_summary")
                .select("total_calories, total_protein, summary_date")
                .eq("user_id", user_id)
                .gte("summary_date", week_ago_date)
                .gt("total_calories", 0)
                .execute()
            )
            rows = health_rows.data or []
            if len(rows) >= 3:
                avg_cal = sum(r.get("total_calories", 0) for r in rows) / len(rows)
                # Consistently under 1400 cal is a pattern worth noting
                if avg_cal < 1400:
                    return {
                        "type": "health_pattern",
                        "context": {
                            "pattern": "low_intake",
                            "days_logged": len(rows),
                            "avg_calories": round(avg_cal),
                        },
                    }
        except Exception:
            pass

        # Priority 4: Something emotionally significant the user mentioned recently
        try:
            recent_msgs = (
                supabase.table("messages")
                .select("body, created_at")
                .eq("owner_user_id", user_id)
                .eq("processed", True)
                .order("created_at", desc=True)
                .limit(30)
                .execute()
            )
            emotional_keywords = ["stressed", "worried", "excited", "nervous", "happy", "sad",
                                   "anxious", "scared", "proud", "frustrated", "overwhelmed",
                                   "planning", "hoping", "dreading"]
            for msg in (recent_msgs.data or []):
                body = (msg.get("body") or "").lower()
                if any(kw in body for kw in emotional_keywords):
                    return {
                        "type": "user_mention",
                        "context": {
                            "snippet": msg.get("body", "")[:200],
                        },
                    }
        except Exception:
            pass

        # Priority 5: Open reflection fallback
        return {
            "type": "open_reflection",
            "context": {},
        }

    async def _generate_opening(self, user_id: str, seed: dict) -> Optional[str]:
        """
        Generate a 1-3 sentence opening message using Claude with World Model context.
        The message must sound like it comes from someone who pays attention, not an AI.
        """
        seed_type = seed.get("type", "open_reflection")
        context = seed.get("context", {})

        # Build the system prompt — Genie's voice for nightly conversations
        system_prompt = """You are Personal Genie sending one warm, thoughtful message to check in with the user.

This is NOT:
- A task reminder
- An update about their relationships
- A health notification
- A feature announcement

This IS:
- A gentle, attentive check-in from someone who pays attention
- One message that opens a door, nothing more
- The kind of thing a wise friend might text at 9pm

Rules (non-negotiable):
- 1–3 sentences MAXIMUM
- Never explain why you're reaching out
- Never say "I noticed" or "based on your data"
- Never start with "Hey" or "Hi"
- Sound like a person, not a product
- End with something that implicitly or explicitly invites a response
- No emojis"""

        # Build the user message with seed context
        if seed_type == "third_party_signal":
            signal_type = context.get("signal_type", "")
            user_msg = (
                f"The seed: someone close to the user recently expressed concern or feeling about them. "
                f"Signal type: {signal_type}. "
                f"Do NOT reveal who or what the signal was. Open with something attentive about how the user is doing."
            )

        elif seed_type == "relationship_pattern":
            person_name = context.get("person_name", "someone")
            days_silent = context.get("days_silent", 14)
            rel_type = context.get("relationship_type", "")
            user_msg = (
                f"The seed: the user hasn't meaningfully connected with {person_name} ({rel_type}) "
                f"in {days_silent} days. Open with something that touches on this relationship gently — "
                f"not as a task, but as a reflection. Don't mention the time gap explicitly."
            )

        elif seed_type == "health_pattern":
            pattern = context.get("pattern", "")
            days_logged = context.get("days_logged", 0)
            avg_cal = context.get("avg_calories", 0)
            user_msg = (
                f"The seed: the user has been showing up consistently ({days_logged} days of logging), "
                f"eating around {avg_cal} calories on average. Open with something that acknowledges "
                f"their consistency and asks how their body feels — not about numbers."
            )

        elif seed_type == "user_mention":
            snippet = context.get("snippet", "")
            user_msg = (
                f"The seed: the user recently mentioned something emotionally significant: '{snippet}'. "
                f"Reference this gently, as if you've been thinking about it. Don't quote it directly."
            )

        else:  # open_reflection
            # Load a bit of World Model context for grounding
            world_context = await self._get_world_model_snippet(user_id)
            user_msg = (
                f"Fallback — no specific seed available. Use this World Model context to find something warm: "
                f"{world_context}. "
                f"Ask one open, reflective question. Make it feel personal, not generic."
            )

        try:
            opening = _call_claude(system_prompt, user_msg)
            opening = opening.strip().strip('"').strip("'")
            # Truncate to reasonable length — this should be short
            if len(opening) > 500:
                opening = opening[:500].rsplit(".", 1)[0] + "."
            return opening
        except Exception as e:
            logger.error(f"NightlyConversations: Claude failed to generate opening for {user_id}: {e}")
            return None

    async def _get_world_model_snippet(self, user_id: str) -> str:
        """
        Pull a brief summary of the user's world model for the fallback seed.
        Returns a short text string for Claude context.
        """
        parts = []
        try:
            people = db.get_people_for_user(user_id)
            if people:
                top = people[0]
                parts.append(f"Closest person: {top.get('name')} ({top.get('relationship_type', '')})")

            user_row = db.get_user_by_id(user_id)
            if user_row:
                parts.append(f"User name: {user_row.get('name', 'the user')}")

            from services.emotional_state import get_current_state
            state = get_current_state(user_id)
            mood = state.get("inferred_mood", "neutral")
            parts.append(f"Current mood: {mood}")
        except Exception:
            pass

        return "; ".join(parts) if parts else "No context available"
