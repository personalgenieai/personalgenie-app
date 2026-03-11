"""
services/rule_engine.py — Rule Engine: evaluate user-defined rules and fire actions.

Rules sit in the `genie_rules` table and are evaluated every 15 minutes.
Each rule has a trigger_type, trigger_config (JSONB), action_type, and action_config (JSONB).

Trigger types: time, genie_observation, health_metric, music_playing, calendar_event
Action types: notify_ios, send_whatsapp, send_reminder, play_music, start_conversation

Deduplication: rule_executions table tracks fired rules with per-type cooldowns.
Error isolation: one rule failing never affects others.
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import database as db

logger = logging.getLogger(__name__)

# Cooldown hours per trigger type — minimum hours between firings of the same rule
COOLDOWN_HOURS = {
    "time": 20,
    "genie_observation": 48,
    "health_metric": 20,
    "music_playing": 1,
    "calendar_event": 1,
}

# Day name mapping for trigger_config.days
DAY_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}


class RuleEngine:
    """
    Evaluates all active genie_rules for all users on a 15-minute cycle.
    Each rule is isolated — errors in one rule do not affect others.
    """

    async def evaluate_all_users(self) -> dict:
        """
        Run rule evaluation for every consented user.
        Returns summary stats: {users_checked, rules_fired, errors}
        """
        users_checked = 0
        total_fired = 0
        total_errors = 0

        try:
            result = db.get_db().table("users").select("id, phone").eq("whatsapp_consented", True).execute()
            users = result.data or []
        except Exception as e:
            logger.error(f"RuleEngine: could not load users: {e}")
            return {"users_checked": 0, "rules_fired": 0, "errors": 1}

        for user in users:
            user_id = user.get("id")
            phone = user.get("phone", "")
            if not user_id or not phone:
                continue
            users_checked += 1
            try:
                fired = await self.evaluate_for_user(user_id, phone)
                total_fired += len(fired)
            except Exception as e:
                logger.error(f"RuleEngine: error evaluating user {user_id}: {e}")
                total_errors += 1

        logger.info(f"RuleEngine: checked {users_checked} users, fired {total_fired} rules, {total_errors} errors")
        return {"users_checked": users_checked, "rules_fired": total_fired, "errors": total_errors}

    async def evaluate_for_user(self, user_id: str, phone: str) -> list:
        """
        Evaluate all active rules for a single user.
        Returns list of fired rule IDs.
        """
        fired_ids = []

        try:
            result = (
                db.get_db()
                .table("genie_rules")
                .select("*")
                .eq("user_id", user_id)
                .eq("is_active", True)
                .execute()
            )
            rules = result.data or []
        except Exception as e:
            logger.error(f"RuleEngine: could not load rules for user {user_id}: {e}")
            return fired_ids

        for rule in rules:
            rule_id = rule.get("id")
            try:
                # Check cooldown before evaluating trigger
                if self._is_in_cooldown(rule):
                    continue

                triggered = await self._check_trigger(rule, user_id)
                if not triggered:
                    continue

                success = await self._execute_action(rule, user_id, phone)
                if success:
                    self._record_execution(rule_id, user_id)
                    self._update_last_fired(rule_id)
                    fired_ids.append(rule_id)

            except Exception as e:
                logger.error(f"RuleEngine: rule {rule_id} failed for user {user_id}: {e}")
                # Continue to next rule — isolation is critical

        return fired_ids

    async def _check_trigger(self, rule: dict, user_id: str) -> bool:
        """
        Evaluate whether a rule's trigger condition is currently met.
        Returns True if the rule should fire.
        """
        trigger_type = rule.get("trigger_type", "")
        config = rule.get("trigger_config") or {}

        try:
            if trigger_type == "time":
                return await self._check_time_trigger(config, user_id)
            elif trigger_type == "genie_observation":
                return await self._check_observation_trigger(config, user_id)
            elif trigger_type == "health_metric":
                return await self._check_health_metric_trigger(config, user_id)
            elif trigger_type == "music_playing":
                return await self._check_music_trigger(config, user_id)
            elif trigger_type == "calendar_event":
                return await self._check_calendar_trigger(config, user_id)
            else:
                logger.warning(f"RuleEngine: unknown trigger_type '{trigger_type}' for rule {rule.get('id')}")
                return False
        except Exception as e:
            logger.error(f"RuleEngine: trigger check failed for rule {rule.get('id')}: {e}")
            return False

    async def _check_time_trigger(self, config: dict, user_id: str) -> bool:
        """
        Fire if current UTC hour matches AND (optionally) today is in the days list
        AND (optionally) the extra condition is met.
        """
        now_utc = datetime.now(timezone.utc)
        required_hour = config.get("hour")
        if required_hour is None:
            return False

        if now_utc.hour != int(required_hour):
            return False

        # Check days filter
        days = config.get("days")
        if days:
            today_name = now_utc.strftime("%a").lower()[:3]
            if today_name not in [d.lower()[:3] for d in days]:
                return False

        # Check optional condition
        condition = config.get("condition")
        if condition:
            try:
                today_str = date.today().isoformat()
                result = (
                    db.get_db()
                    .table("health_daily_summary")
                    .select("total_calories, nudge_sent")
                    .eq("user_id", user_id)
                    .eq("summary_date", today_str)
                    .execute()
                )
                row = result.data[0] if result.data else {}

                if condition == "no_food_logged_today":
                    return (row.get("total_calories") or 0) == 0

                elif condition == "habit_at_risk":
                    # days_logging > 3 AND today no food AND yesterday no food
                    from services.nutrition import get_days_logging, get_daily_summary
                    days_logging = get_days_logging(user_id)
                    if days_logging <= 3:
                        return False
                    today_summary = get_daily_summary(user_id)
                    if (today_summary.get("total_calories") or 0) > 0:
                        return False
                    from datetime import timedelta
                    yesterday = (date.today() - timedelta(days=1)).isoformat()
                    yesterday_result = (
                        db.get_db()
                        .table("health_daily_summary")
                        .select("total_calories")
                        .eq("user_id", user_id)
                        .eq("summary_date", yesterday)
                        .execute()
                    )
                    yesterday_row = yesterday_result.data[0] if yesterday_result.data else {}
                    return (yesterday_row.get("total_calories") or 0) == 0

            except Exception as e:
                logger.warning(f"RuleEngine: time condition '{condition}' check failed: {e}")
                return False

        return True

    async def _check_observation_trigger(self, config: dict, user_id: str) -> bool:
        """
        person_name + silence_days: check last_meaningful_exchange.
        observation = "habit_at_risk": logging streak at risk.
        """
        person_name = config.get("person_name")
        silence_days = config.get("silence_days")
        observation = config.get("observation")

        if person_name and silence_days:
            try:
                people = db.get_people_for_user(user_id)
                person = next(
                    (p for p in people if p.get("name", "").lower() == person_name.lower()),
                    None,
                )
                if not person:
                    return False
                last_exchange = person.get("last_meaningful_exchange")
                if not last_exchange:
                    return True  # Never spoken — counts as silent
                last_dt = datetime.fromisoformat(last_exchange.replace("Z", "+00:00"))
                cutoff = datetime.now(timezone.utc) - timedelta(days=int(silence_days))
                return last_dt < cutoff
            except Exception as e:
                logger.warning(f"RuleEngine: observation person check failed: {e}")
                return False

        if observation == "habit_at_risk":
            try:
                from services.nutrition import get_days_logging, get_daily_summary
                days_logging = get_days_logging(user_id)
                if days_logging <= 3:
                    return False
                today_summary = get_daily_summary(user_id)
                if (today_summary.get("total_calories") or 0) > 0:
                    return False
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                result = (
                    db.get_db()
                    .table("health_daily_summary")
                    .select("total_calories")
                    .eq("user_id", user_id)
                    .eq("summary_date", yesterday)
                    .execute()
                )
                yesterday_row = result.data[0] if result.data else {}
                return (yesterday_row.get("total_calories") or 0) == 0
            except Exception as e:
                logger.warning(f"RuleEngine: habit_at_risk check failed: {e}")
                return False

        return False

    async def _check_health_metric_trigger(self, config: dict, user_id: str) -> bool:
        """
        Query today's health_daily_summary and evaluate metric condition.
        metric: "calories" | "protein" | "trained"
        operator: "lt" | "gt" | "eq"
        value: float | bool
        """
        metric = config.get("metric")
        operator = config.get("operator")
        threshold = config.get("value")

        if not metric or not operator or threshold is None:
            return False

        try:
            today_str = date.today().isoformat()
            result = (
                db.get_db()
                .table("health_daily_summary")
                .select("*")
                .eq("user_id", user_id)
                .eq("summary_date", today_str)
                .execute()
            )
            row = result.data[0] if result.data else {}

            if metric == "calories":
                actual = row.get("total_calories") or 0
            elif metric == "protein":
                actual = row.get("total_protein") or 0
            elif metric == "trained":
                actual = bool(row.get("trained_today", False))
                threshold = bool(threshold)
            else:
                logger.warning(f"RuleEngine: unknown health metric '{metric}'")
                return False

            if operator == "lt":
                return actual < threshold
            elif operator == "gt":
                return actual > threshold
            elif operator == "eq":
                return actual == threshold
            else:
                logger.warning(f"RuleEngine: unknown operator '{operator}'")
                return False

        except Exception as e:
            logger.warning(f"RuleEngine: health metric check failed: {e}")
            return False

    async def _check_music_trigger(self, config: dict, user_id: str) -> bool:
        """
        Check Spotify currently playing. Skip gracefully if no Spotify connection.
        mood: loose keyword match against track/artist name
        artist: artist name match
        """
        try:
            from services.spotify_client import SpotifyClient
            client = SpotifyClient(user_id)
            data = await client.get_currently_playing()
            if not data or not data.get("is_playing") or not data.get("item"):
                return False

            item = data["item"]
            track_name = (item.get("name") or "").lower()
            artist_names = " ".join(
                a["name"] for a in item.get("artists", [])
            ).lower()

            mood = config.get("mood", "").lower()
            artist = config.get("artist", "").lower()

            if mood and mood not in track_name and mood not in artist_names:
                return False
            if artist and artist not in artist_names:
                return False

            return True

        except RuntimeError:
            # No Spotify connection — skip silently
            return False
        except Exception as e:
            logger.warning(f"RuleEngine: music trigger check failed (skipping): {e}")
            return False

    async def _check_calendar_trigger(self, config: dict, user_id: str) -> bool:
        """
        Check calendar_events for events within the next N hours.
        hours_before: int — how many hours ahead to look
        title_contains: str — optional keyword filter on event title
        """
        hours_before = config.get("hours_before", 1)
        title_filter = (config.get("title_contains") or "").lower()

        try:
            now = datetime.now(timezone.utc)
            window_end = now + timedelta(hours=int(hours_before))

            result = (
                db.get_db()
                .table("calendar_events")
                .select("title, start_time")
                .eq("user_id", user_id)
                .gte("start_time", now.isoformat())
                .lte("start_time", window_end.isoformat())
                .execute()
            )
            events = result.data or []

            if not events:
                return False

            if title_filter:
                return any(title_filter in (e.get("title") or "").lower() for e in events)

            return True

        except Exception as e:
            logger.warning(f"RuleEngine: calendar trigger check failed: {e}")
            return False

    async def _execute_action(self, rule: dict, user_id: str, phone: str) -> bool:
        """
        Execute the action for a triggered rule.
        Returns True if action was executed successfully.
        """
        action_type = rule.get("action_type", "")
        config = rule.get("action_config") or {}

        try:
            if action_type in ("notify_ios", "send_whatsapp", "send_reminder"):
                return await self._action_send_message(rule, user_id, phone, config)
            elif action_type == "play_music":
                return await self._action_play_music(rule, user_id, config)
            elif action_type == "start_conversation":
                return await self._action_start_conversation(rule, user_id, phone, config)
            else:
                logger.warning(f"RuleEngine: unknown action_type '{action_type}' for rule {rule.get('id')}")
                return False
        except Exception as e:
            logger.error(f"RuleEngine: action execution failed for rule {rule.get('id')}: {e}")
            return False

    async def _action_send_message(self, rule: dict, user_id: str, phone: str, config: dict) -> bool:
        """Send a WhatsApp message, interpolating {person_name} if available."""
        from services.whatsapp import send_message
        message = config.get("message", "")
        if not message:
            logger.warning(f"RuleEngine: send action has no message for rule {rule.get('id')}")
            return False

        # Interpolate person_name from trigger_config if available
        trigger_config = rule.get("trigger_config") or {}
        person_name = trigger_config.get("person_name", "")
        if person_name:
            message = message.replace("{person_name}", person_name)

        try:
            send_message(phone, message, user_id=user_id)
            return True
        except Exception as e:
            logger.error(f"RuleEngine: send_message failed for user {user_id}: {e}")
            return False

    async def _action_play_music(self, rule: dict, user_id: str, config: dict) -> bool:
        """Play music via Spotify. Skip gracefully if no Spotify connection."""
        try:
            from services.spotify_client import SpotifyClient
            query = config.get("query", "")
            device_name = config.get("device_name")
            if not query:
                logger.warning(f"RuleEngine: play_music action has no query for rule {rule.get('id')}")
                return False
            client = SpotifyClient(user_id)
            await client.play(query=query, device_name=device_name)
            return True
        except RuntimeError:
            # No Spotify connection — skip silently
            logger.info(f"RuleEngine: no Spotify connection for user {user_id}, skipping play_music")
            return False
        except Exception as e:
            logger.warning(f"RuleEngine: play_music failed for user {user_id} (skipping): {e}")
            return False

    async def _action_start_conversation(self, rule: dict, user_id: str, phone: str, config: dict) -> bool:
        """Start a Genie conversation with the specified person."""
        from services.genie_conversations import start_conversation, should_initiate
        person_name = config.get("person_name", "")
        topic = config.get("topic", "rule_fired")

        if not person_name:
            logger.warning(f"RuleEngine: start_conversation has no person_name for rule {rule.get('id')}")
            return False

        # Find the person in the graph
        people = db.get_people_for_user(user_id)
        person = next(
            (p for p in people if p.get("name", "").lower() == person_name.lower()),
            None,
        )
        if not person:
            logger.info(f"RuleEngine: person '{person_name}' not found in graph for user {user_id}")
            return False

        person_id = person["id"]
        if not should_initiate(user_id, person_id):
            logger.info(f"RuleEngine: conversation with {person_name} too recent, skipping")
            return False

        conv_id = start_conversation(user_id, person_id, "relationship_check", phone)
        return bool(conv_id)

    # ── Deduplication helpers ────────────────────────────────────────────────

    def _is_in_cooldown(self, rule: dict) -> bool:
        """
        Check rule_executions table to see if this rule fired within its cooldown window.
        Returns True if still in cooldown (should NOT fire again).
        """
        rule_id = rule.get("id")
        trigger_type = rule.get("trigger_type", "time")
        cooldown_hours = COOLDOWN_HOURS.get(trigger_type, 20)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat()

        try:
            result = (
                db.get_db()
                .table("rule_executions")
                .select("id")
                .eq("rule_id", rule_id)
                .gte("fired_at", cutoff)
                .execute()
            )
            return bool(result.data)
        except Exception as e:
            logger.warning(f"RuleEngine: cooldown check failed for rule {rule_id}: {e}")
            return False  # If we can't check, allow it to fire

    def _record_execution(self, rule_id: str, user_id: str) -> None:
        """Insert a record into rule_executions table after firing."""
        try:
            db.get_db().table("rule_executions").insert({
                "id": str(uuid.uuid4()),
                "rule_id": rule_id,
                "user_id": user_id,
                "fired_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.error(f"RuleEngine: could not record execution for rule {rule_id}: {e}")

    def _update_last_fired(self, rule_id: str) -> None:
        """Update last_fired_at on the genie_rules record."""
        try:
            db.get_db().table("genie_rules").update({
                "last_fired_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", rule_id).execute()
        except Exception as e:
            logger.warning(f"RuleEngine: could not update last_fired_at for rule {rule_id}: {e}")
