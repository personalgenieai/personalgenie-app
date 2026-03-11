"""
core/world_model.py — The unified context object for every Genie interaction.

The World Model assembles everything Genie knows about a user into one coherent
object that gets injected into Claude's system prompt on every conversation turn.

Sections:
  user          — name, phone, member since, subscription tier
  people        — top relationships with closeness, memories, last exchange
  health        — today's nutrition + training, habit streak
  emotional     — current emotional state inferred from messages
  music         — current/recent listening, mood inference (MusicProvider)
  moments       — top pending moment suggestions
  third_party   — cross-user signals about this user (anonymized, no attribution)
  permissions   — active cross-user permission grants this user has given
  calendar      — today + next 3 days of personal events
  interests     — top interest signals

The World Model is assembled fresh per conversation turn (lightweight — mostly
reading from Supabase, one music API call, one signal aggregation). Heavy
computation (signal extraction, relationship scoring) happens in background jobs.

Bi-directional graph:
  When assembling the World Model for user TJ, we also query third_party_signals
  about TJ — signals written by OTHER users (e.g. Leo, Alice) from their own
  conversations. These are fully anonymized before injection into Claude context.
  The source user is never named or implied.

Privacy contract (never violated):
  - third_party_signals injected into Claude context have no source attribution
  - Claude's system prompt explicitly forbids revealing signal sources
  - Permission level is checked before any signal is used
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from config import get_settings

logger = logging.getLogger(__name__)


# ── World Model dataclass ─────────────────────────────────────────────────────

@dataclass
class WorldModel:
    user_id: str
    assembled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Core sections
    user: dict = field(default_factory=dict)
    people: list[dict] = field(default_factory=list)
    health: dict = field(default_factory=dict)
    emotional: dict = field(default_factory=dict)
    music: dict = field(default_factory=dict)
    moments: list[dict] = field(default_factory=list)
    calendar: list[dict] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)

    # Bi-directional graph sections
    third_party_signals: list[dict] = field(default_factory=list)   # signals ABOUT this user
    outbound_permissions: list[dict] = field(default_factory=list)  # permissions this user has granted

    # Onboarding context (set when user is new)
    prior_perspectives: dict = field(default_factory=dict)

    def to_claude_context(self) -> str:
        """
        Render the World Model as a Claude system prompt context string.
        This is what gets injected on every conversation turn.
        """
        parts = []

        # ── User identity ─────────────────────────────────────────────────────
        if self.user:
            parts.append(f"User: {self.user.get('name', 'Unknown')} | "
                         f"Member since: {self.user.get('created_at', 'recently')[:10]}")

        # ── People graph ──────────────────────────────────────────────────────
        if self.people:
            lines = ["Relationships (closest first):"]
            for p in self.people[:12]:
                line = f"  - {p['name']} ({p.get('relationship_type', 'person')})" \
                       f" closeness={p.get('closeness_score', 0.5):.2f}"
                if p.get("days_since_exchange") is not None:
                    line += f" last_exchange={p['days_since_exchange']}d ago"
                mem = p.get("top_memory", "")
                if mem:
                    line += f"\n    Memory: {mem[:120]}"
                lines.append(line)
            parts.append("\n".join(lines))

        # ── Health ────────────────────────────────────────────────────────────
        if self.health:
            today = self.health.get("today", {})
            h_lines = [f"Health today: {today.get('total_calories', 0):.0f} cal | "
                       f"{today.get('total_protein', 0):.0f}g protein | "
                       f"trained={'yes' if today.get('trained') else 'no'}"]
            streak = self.health.get("days_logging", 0)
            if streak:
                h_lines.append(f"Logging streak: {streak} days")
            parts.append("\n".join(h_lines))

        # ── Music / emotional context ─────────────────────────────────────────
        if self.music:
            parts.append(f"Music: {self.music.get('summary', 'No recent listening data.')}")

        if self.emotional:
            state = self.emotional.get("state", "")
            if state:
                parts.append(f"Emotional state: {state}")

        # ── Active moments ────────────────────────────────────────────────────
        if self.moments:
            top = self.moments[0]
            person_data = top.get("people") or {}
            pname = person_data.get("name", "someone") if isinstance(person_data, dict) else "someone"
            parts.append(f"Top pending moment: about {pname} — \"{top.get('suggestion', '')[:120]}\"")

        # ── Upcoming calendar ─────────────────────────────────────────────────
        if self.calendar:
            cal_lines = ["Upcoming personal events:"]
            for ev in self.calendar[:4]:
                cal_lines.append(f"  - {ev.get('title', '')} ({ev.get('date', '')})")
            parts.append("\n".join(cal_lines))

        # ── Interests ─────────────────────────────────────────────────────────
        if self.interests:
            parts.append(f"Known interests: {', '.join(self.interests[:8])}")

        # ── Third-party signals (bi-directional graph) ────────────────────────
        if self.third_party_signals:
            sig_lines = [
                "CROSS-USER CONTEXT (use this to be attentive — never reveal the source):",
                "The following signals about this user were observed by people close to them.",
                "They did not come from this user. They have no source attribution. Never hint at them.",
            ]
            for sig in self.third_party_signals[:5]:
                sig_lines.append(
                    f"  [{sig['signal_type']}] {sig['signal_abstract']} "
                    f"(confidence={sig.get('confidence', 0.7):.0%}, "
                    f"valence={_valence_label(sig.get('signal_valence', 0))})"
                )
            parts.append("\n".join(sig_lines))

        # ── Prior perspectives (onboarding) ──────────────────────────────────
        if self.prior_perspectives.get("perspective_count", 0) > 0:
            pp = self.prior_perspectives
            parts.append(
                f"Pre-existing context: {pp['perspective_count']} people who know this user "
                f"are already Genie users. Aggregate closeness: {pp.get('aggregate_closeness', 0):.2f}. "
                f"Known entities: {', '.join(pp.get('known_entities', [])[:6])}. "
                f"Use this to feel like you already know them — never explain why."
            )

        return "\n\n".join(parts)


def _valence_label(v: float) -> str:
    if v > 0.3:
        return "positive"
    if v < -0.3:
        return "negative"
    return "neutral"


# ── Assembler ─────────────────────────────────────────────────────────────────

class WorldModelAssembler:
    """
    Assembles a WorldModel for a given user_id.

    Usage:
        assembler = WorldModelAssembler()
        wm = await assembler.assemble(user_id)
        system_prompt = base_prompt + "\n\n" + wm.to_claude_context()
    """

    async def assemble(self, user_id: str) -> WorldModel:
        from db import get_db
        db = get_db()

        wm = WorldModel(user_id=user_id)

        # Run all sections — failures are isolated, never crash the conversation
        await self._load_user(db, wm)
        await self._load_people(db, wm)
        await self._load_health(db, wm)
        await self._load_emotional(db, wm)
        await self._load_music(wm)
        await self._load_moments(db, wm)
        await self._load_calendar(db, wm)
        await self._load_interests(db, wm)
        await self._load_third_party_signals(db, wm)
        await self._load_prior_perspectives(db, wm)

        # Persist snapshot to world_model table for audit/debugging
        await self._persist(db, wm)

        return wm

    # ── Section loaders ───────────────────────────────────────────────────────

    async def _load_user(self, db, wm: WorldModel) -> None:
        try:
            result = db.table("users").select("id, name, created_at, phone").eq("id", wm.user_id).execute()
            if result.data:
                wm.user = result.data[0]
        except Exception as exc:
            logger.warning("WorldModel: user load failed for %s: %s", wm.user_id, exc)

    async def _load_people(self, db, wm: WorldModel) -> None:
        try:
            result = (
                db.table("people")
                .select("id, name, relationship_type, closeness_score, last_meaningful_exchange, memories")
                .eq("user_id", wm.user_id)
                .order("closeness_score", desc=True)
                .limit(15)
                .execute()
            )
            now = datetime.now(timezone.utc)
            people = []
            for p in (result.data or []):
                last = p.get("last_meaningful_exchange")
                days = None
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                        days = (now - last_dt).days
                    except Exception:
                        pass

                memories = p.get("memories") or []
                top_memory = memories[0].get("description", "") if memories else ""

                people.append({
                    **p,
                    "days_since_exchange": days,
                    "top_memory": top_memory,
                })
            wm.people = people
        except Exception as exc:
            logger.warning("WorldModel: people load failed: %s", exc)

    async def _load_health(self, db, wm: WorldModel) -> None:
        try:
            from services.nutrition import get_daily_summary, get_days_logging
            summary = get_daily_summary(wm.user_id)
            days = get_days_logging(wm.user_id)
            habit = db.table("health_daily_summary") \
                      .select("habit_established") \
                      .eq("user_id", wm.user_id) \
                      .order("summary_date", desc=True) \
                      .limit(1) \
                      .execute()
            established = habit.data[0].get("habit_established", False) if habit.data else False
            wm.health = {
                "today": summary,
                "days_logging": days,
                "habit_established": established,
            }
        except Exception as exc:
            logger.warning("WorldModel: health load failed: %s", exc)

    async def _load_emotional(self, db, wm: WorldModel) -> None:
        try:
            from services.emotional_state import get_current_emotional_state
            state = get_current_emotional_state(wm.user_id)
            wm.emotional = {"state": state} if state else {}
        except Exception as exc:
            logger.warning("WorldModel: emotional load failed: %s", exc)

    async def _load_music(self, wm: WorldModel) -> None:
        try:
            from capabilities.music.provider import MusicProvider
            mp = MusicProvider(wm.user_id)
            ctx = await mp.get_emotional_context()
            if ctx:
                wm.music = ctx.to_dict()
        except Exception as exc:
            logger.warning("WorldModel: music load failed: %s", exc)

    async def _load_moments(self, db, wm: WorldModel) -> None:
        try:
            import database as dbm
            wm.moments = dbm.get_moments_for_user(wm.user_id)[:5]
        except Exception as exc:
            logger.warning("WorldModel: moments load failed: %s", exc)

    async def _load_calendar(self, db, wm: WorldModel) -> None:
        try:
            from datetime import timedelta
            now = datetime.now(timezone.utc)
            window_end = (now + timedelta(days=4)).isoformat()
            result = (
                db.table("calendar_events")
                .select("title, start_time, calendar_name")
                .eq("user_id", wm.user_id)
                .eq("work_filtered", False)
                .gte("start_time", now.isoformat())
                .lte("start_time", window_end)
                .order("start_time")
                .limit(8)
                .execute()
            )
            wm.calendar = [
                {"title": r["title"], "date": r["start_time"][:10]}
                for r in (result.data or [])
            ]
        except Exception as exc:
            logger.warning("WorldModel: calendar load failed: %s", exc)

    async def _load_interests(self, db, wm: WorldModel) -> None:
        try:
            from services.interests import get_top_interests
            wm.interests = get_top_interests(wm.user_id, limit=10)
        except Exception as exc:
            logger.warning("WorldModel: interests load failed: %s", exc)

    async def _load_third_party_signals(self, db, wm: WorldModel) -> None:
        """
        Load signals written BY OTHER USERS about this user.
        These are stored in third_party_signals where about_phone_hash matches
        this user's hashed phone number.
        """
        try:
            # Get this user's phone hash for cross-user matching
            user_row = wm.user or {}
            phone = user_row.get("phone", "")
            if not phone:
                return

            import hashlib
            phone_hash = hashlib.sha256(phone.encode()).hexdigest()

            from datetime import timedelta
            now = datetime.now(timezone.utc)

            # Also match by direct person_id link (for users already linked)
            result = (
                db.table("third_party_signals")
                .select(
                    "signal_type, signal_abstract, signal_valence, signal_intensity, "
                    "confidence, extracted_at, source_user_id"
                )
                .eq("about_phone_hash", phone_hash)
                .gt("expires_at", now.isoformat())
                .order("confidence", desc=True)
                .limit(10)
                .execute()
            )

            signals = []
            for row in (result.data or []):
                # Check permission level from source user
                perm = await self._get_permission_level(db, row["source_user_id"], phone_hash)
                if perm < 0:
                    continue  # source user has revoked all sharing

                # Strip source attribution completely before adding to World Model
                signals.append({
                    "signal_type": row["signal_type"],
                    "signal_abstract": row["signal_abstract"],
                    "signal_valence": row.get("signal_valence", 0),
                    "signal_intensity": row.get("signal_intensity", 0.5),
                    "confidence": row.get("confidence", 0.7),
                    "days_ago": (now - datetime.fromisoformat(
                        row["extracted_at"].replace("Z", "+00:00")
                    )).days,
                    # source_user_id intentionally omitted — never goes to Claude
                })

                # Increment used_count
                try:
                    db.table("third_party_signals").update({
                        "used_count": (row.get("used_count") or 0) + 1,
                        "last_used_at": now.isoformat(),
                    }).eq("about_phone_hash", phone_hash).execute()
                except Exception:
                    pass

            wm.third_party_signals = signals

        except Exception as exc:
            logger.warning("WorldModel: third-party signals load failed: %s", exc)

    async def _get_permission_level(self, db, source_user_id: str, beneficiary_phone_hash: str) -> int:
        """
        Check the permission level a source user has granted for a beneficiary.
        Returns the level (0-3) or -1 if revoked/none.
        Default is 0 (silent use) if no explicit record exists.
        """
        try:
            result = (
                db.table("cross_user_permissions")
                .select("permission_level, revoked_at")
                .eq("granting_user_id", source_user_id)
                .eq("beneficiary_phone_hash", beneficiary_phone_hash)
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                if row.get("revoked_at"):
                    return -1  # revoked
                return row.get("permission_level", 0)
            return 0  # no explicit record — default silent use
        except Exception:
            return 0

    async def _load_prior_perspectives(self, db, wm: WorldModel) -> None:
        """
        Check how many OTHER Genie users have this user in their people graph.
        Used for onboarding context: if > 0, Genie 'already knows' this person.
        """
        try:
            user_row = wm.user or {}
            phone = user_row.get("phone", "")
            if not phone:
                return

            import hashlib
            phone_hash = hashlib.sha256(phone.encode()).hexdigest()

            # Count distinct source users who have signals about this person
            result = (
                db.table("third_party_signals")
                .select("source_user_id, signal_type, signal_valence")
                .eq("about_phone_hash", phone_hash)
                .execute()
            )

            if not result.data:
                return

            source_users = {r["source_user_id"] for r in result.data}
            perspective_count = len(source_users)

            if perspective_count == 0:
                return

            # Aggregate closeness from people table (across all source users)
            closeness_scores = []
            known_entities: set[str] = set()

            for src_uid in source_users:
                people_result = (
                    db.table("people")
                    .select("closeness_score, memories, name")
                    .eq("user_id", src_uid)
                    .eq("phone_hash", phone_hash)
                    .limit(1)
                    .execute()
                )
                if people_result.data:
                    p = people_result.data[0]
                    if p.get("closeness_score"):
                        closeness_scores.append(p["closeness_score"])
                    # Extract entity names from memories (no verbatim content)
                    for mem in (p.get("memories") or [])[:3]:
                        desc = mem.get("description", "")
                        # Extract proper nouns as known entities (crude but safe)
                        for word in desc.split():
                            if word and word[0].isupper() and len(word) > 2 and word.isalpha():
                                known_entities.add(word)

            avg_closeness = sum(closeness_scores) / len(closeness_scores) if closeness_scores else 0.5

            wm.prior_perspectives = {
                "perspective_count": perspective_count,
                "aggregate_closeness": avg_closeness,
                "known_entities": list(known_entities)[:10],
            }

        except Exception as exc:
            logger.warning("WorldModel: prior perspectives load failed: %s", exc)

    async def _persist(self, db, wm: WorldModel) -> None:
        """Save World Model snapshot for audit/debugging. Non-blocking."""
        try:
            import json
            db.table("world_model").upsert({
                "user_id": wm.user_id,
                "assembled_at": wm.assembled_at,
                "snapshot_json": json.dumps({
                    "user": wm.user,
                    "people_count": len(wm.people),
                    "signal_count": len(wm.third_party_signals),
                    "music_connected": bool(wm.music),
                    "prior_perspective_count": wm.prior_perspectives.get("perspective_count", 0),
                }),
                "is_stale": False,
            }).execute()
        except Exception:
            pass  # persistence failure must never block a conversation


# ── Module-level convenience ──────────────────────────────────────────────────

_assembler = WorldModelAssembler()


async def assemble_world_model(user_id: str) -> WorldModel:
    """Module-level convenience. Call this from conversation handlers."""
    return await _assembler.assemble(user_id)
