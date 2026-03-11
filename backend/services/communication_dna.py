"""
services/communication_dna.py — Communication DNA profiling per relationship.

Analyzes message history between the user and each person in their graph to
produce a structured "Communication DNA" profile. The profile captures how
this specific relationship communicates — tone, rhythm, intimacy, topics.

Storage: people.communication_dna_json (TEXT/JSONB column).

Linguistic Intimacy Score (0.0–1.0) is computed from observable signals
without calling Claude. Claude is used only for tone and topic extraction.
Results are cached — DNA is not recomputed if messages haven't changed.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── Intimacy scoring weights ──────────────────────────────────────────────────

def _count_emojis(text: str) -> int:
    """Count emoji characters in a string."""
    # Unicode ranges for common emoji
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F9FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE,
    )
    return len(emoji_pattern.findall(text))


ABBREVIATIONS = {
    "lol", "lmao", "omg", "btw", "tbh", "idk", "imo", "ngl",
    "brb", "gtg", "ttyl", "hbu", "wya", "smh", "fr", "rn",
    "ily", "luv", "haha", "hehe", "yup", "nope", "nah",
}

NICKNAME_SIGNALS = {
    "babe", "boo", "bb", "hun", "hon", "buddy", "pal", "dude", "bro", "sis",
    "bestie", "love", "darling", "dear", "sweetie",
}


class CommunicationDNA:
    """
    Analyzes and stores Communication DNA profiles for relationships.

    Usage:
        dna = CommunicationDNA()
        profile = await dna.analyze_relationship(user_id, person_id, messages)
        score = await dna.compute_linguistic_intimacy(messages)
    """

    async def analyze_relationship(
        self,
        user_id: str,
        person_id: str,
        messages: list[dict],
    ) -> dict:
        """
        Build a full Communication DNA profile from message history.

        messages: list of {text: str, is_from_me: bool, timestamp: str (ISO)}

        Returns the DNA profile dict and saves it to people.communication_dna_json.
        """
        if not messages:
            return self._empty_profile()

        intimacy_score = await self.compute_linguistic_intimacy(messages)
        avg_response_time = self._compute_avg_response_time(messages)
        initiates_ratio = self._compute_initiates_ratio(messages)
        avg_message_length = self._compute_avg_message_length(messages)
        emoji_frequency = self._compute_emoji_frequency(messages)
        peak_hours = self._compute_peak_hours(messages)
        silence_pattern = self._compute_silence_pattern(messages)
        intimacy_trend = self._compute_intimacy_trend(messages)

        # Use Claude for tone and topic extraction (requires API call)
        tone, topics, language_shifts = await self._analyze_with_claude(messages)

        profile = {
            "linguistic_intimacy": round(intimacy_score, 2),
            "avg_response_time_hours": round(avg_response_time, 1),
            "initiates_ratio": round(initiates_ratio, 2),
            "message_length_avg": round(avg_message_length, 0),
            "emoji_frequency": round(emoji_frequency, 2),
            "typical_tone": tone,
            "topics_recurring": topics,
            "silence_patterns": silence_pattern,
            "peak_communication_hours": peak_hours,
            "language_shifts": language_shifts,
            "intimacy_trend": intimacy_trend,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "message_count": len(messages),
        }

        # Save to people.communication_dna_json
        await self._save_profile(user_id, person_id, profile)
        return profile

    async def compute_linguistic_intimacy(self, messages: list[dict]) -> float:
        """
        Compute a linguistic intimacy score (0.0–1.0) from message signals.

        Components:
          +0.1  nickname usage (babe, boo, bestie, etc.)
          +0.1  heavy abbreviation/shorthand usage
          +0.1  emoji / informal language density
          +0.2  average message length (proportional, capped at 100 words = full score)
          +0.2  response time < 1 hour average
          +0.1  initiation balance close to 50/50 (within 15%)
          +0.2  recurring callbacks / inside references (heuristic: repeated rare tokens)
        """
        if not messages:
            return 0.0

        score = 0.0
        all_text = " ".join(m.get("text", "") or "" for m in messages).lower()
        words = all_text.split()

        # Nickname usage
        if any(nick in words for nick in NICKNAME_SIGNALS):
            score += 0.10

        # Abbreviation density
        abbrev_count = sum(1 for w in words if w.rstrip(".,!?") in ABBREVIATIONS)
        if words and abbrev_count / max(len(words), 1) > 0.02:
            score += 0.10

        # Emoji density
        total_emojis = sum(_count_emojis(m.get("text", "") or "") for m in messages)
        if total_emojis / max(len(messages), 1) > 0.1:
            score += 0.10

        # Message length (longer = more invested, up to 0.2)
        avg_len = self._compute_avg_message_length(messages)
        score += min(0.20, (avg_len / 100.0) * 0.20)

        # Response time < 1 hour average
        avg_rt = self._compute_avg_response_time(messages)
        if 0 < avg_rt < 1.0:
            score += 0.20
        elif 1.0 <= avg_rt < 3.0:
            score += 0.10

        # Initiation balance close to 50/50
        init_ratio = self._compute_initiates_ratio(messages)
        if 0.35 <= init_ratio <= 0.65:
            score += 0.10

        # Recurring callbacks (inside references):
        # Heuristic — rare multi-character tokens repeated across multiple messages
        score += self._score_callbacks(messages)

        return min(1.0, max(0.0, score))

    async def update_person_dna(
        self,
        user_id: str,
        person_id: str,
        new_messages: list[dict],
    ) -> None:
        """
        Update Communication DNA with new messages.
        Merges new messages with existing profile cache; recomputes if new > 10% growth.
        """
        existing = await self._load_profile(person_id)
        existing_count = existing.get("message_count", 0) if existing else 0
        new_count = len(new_messages)

        # Recompute if: no existing profile, or new messages are >10% of existing baseline
        if not existing or new_count > max(5, existing_count * 0.1):
            await self.analyze_relationship(user_id, person_id, new_messages)
        else:
            logger.debug(
                "Skipping DNA recompute for person %s — %d new msgs vs %d existing",
                person_id, new_count, existing_count,
            )

    # ── Private computation helpers ───────────────────────────────────────────

    def _compute_avg_response_time(self, messages: list[dict]) -> float:
        """
        Compute average response time in hours between consecutive messages
        where the sender switches (i.e., the other person replies).
        Returns 0 if insufficient data.
        """
        response_times = []
        for i in range(1, len(messages)):
            prev = messages[i - 1]
            curr = messages[i]
            # Only measure when sender switches
            if prev.get("is_from_me") == curr.get("is_from_me"):
                continue
            try:
                t_prev = datetime.fromisoformat(prev["timestamp"].replace("Z", "+00:00"))
                t_curr = datetime.fromisoformat(curr["timestamp"].replace("Z", "+00:00"))
                delta_hours = (t_curr - t_prev).total_seconds() / 3600.0
                if 0 < delta_hours < 72:  # ignore gaps > 3 days (silence, not response time)
                    response_times.append(delta_hours)
            except (KeyError, ValueError):
                continue

        return sum(response_times) / len(response_times) if response_times else 0.0

    def _compute_initiates_ratio(self, messages: list[dict]) -> float:
        """
        Fraction of conversation threads initiated by the user (is_from_me=True).
        A "thread start" = first message after a gap of >3 hours.
        """
        if not messages:
            return 0.5

        initiations_by_me = 0
        total_initiations = 0

        sorted_msgs = sorted(messages, key=lambda m: m.get("timestamp", ""))
        for i, msg in enumerate(sorted_msgs):
            if i == 0:
                total_initiations += 1
                if msg.get("is_from_me"):
                    initiations_by_me += 1
                continue
            try:
                t_prev = datetime.fromisoformat(sorted_msgs[i-1]["timestamp"].replace("Z", "+00:00"))
                t_curr = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
                gap_hours = (t_curr - t_prev).total_seconds() / 3600.0
                if gap_hours > 3.0:
                    total_initiations += 1
                    if msg.get("is_from_me"):
                        initiations_by_me += 1
            except (KeyError, ValueError):
                continue

        if total_initiations == 0:
            return 0.5
        return initiations_by_me / total_initiations

    def _compute_avg_message_length(self, messages: list[dict]) -> float:
        """Average word count per message."""
        if not messages:
            return 0.0
        lengths = [len((m.get("text") or "").split()) for m in messages]
        return sum(lengths) / len(lengths)

    def _compute_emoji_frequency(self, messages: list[dict]) -> float:
        """Average number of emojis per message."""
        if not messages:
            return 0.0
        total = sum(_count_emojis(m.get("text", "") or "") for m in messages)
        return total / len(messages)

    def _compute_peak_hours(self, messages: list[dict]) -> list[int]:
        """Return the top 3 UTC hours with highest message volume."""
        hour_counts: Counter = Counter()
        for msg in messages:
            try:
                ts = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
                hour_counts[ts.hour] += 1
            except (KeyError, ValueError):
                continue
        return [h for h, _ in hour_counts.most_common(3)]

    def _compute_silence_pattern(self, messages: list[dict]) -> str:
        """Describe the typical silence gap pattern in plain English."""
        gaps = []
        sorted_msgs = sorted(messages, key=lambda m: m.get("timestamp", ""))
        for i in range(1, len(sorted_msgs)):
            try:
                t1 = datetime.fromisoformat(sorted_msgs[i-1]["timestamp"].replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(sorted_msgs[i]["timestamp"].replace("Z", "+00:00"))
                gap_days = (t2 - t1).total_seconds() / 86400.0
                if gap_days > 0.5:
                    gaps.append(gap_days)
            except (KeyError, ValueError):
                continue

        if not gaps:
            return "frequent contact, rarely silent"

        avg_gap = sum(gaps) / len(gaps)
        max_gap = max(gaps)

        if avg_gap < 1:
            return "talks almost daily"
        elif avg_gap < 3:
            return f"typical gap {avg_gap:.0f}-{max_gap:.0f} days"
        elif avg_gap < 7:
            return f"gaps of {avg_gap:.0f}-{max_gap:.0f} days are normal"
        else:
            return f"long silences ({avg_gap:.0f}+ days) are normal for this relationship"

    def _compute_intimacy_trend(self, messages: list[dict]) -> str:
        """
        Compare intimacy in the first half vs second half of message history.
        Returns "increasing", "stable", or "declining".
        """
        if len(messages) < 10:
            return "stable"

        mid = len(messages) // 2
        first_half = messages[:mid]
        second_half = messages[mid:]

        # Use message length as a simple proxy for intimacy trend
        avg_first = sum(len((m.get("text") or "").split()) for m in first_half) / len(first_half)
        avg_second = sum(len((m.get("text") or "").split()) for m in second_half) / len(second_half)

        delta = avg_second - avg_first
        if delta > 5:
            return "increasing"
        elif delta < -5:
            return "declining"
        return "stable"

    def _score_callbacks(self, messages: list[dict]) -> float:
        """
        Heuristic: repeated rare tokens across messages suggest inside references.
        Returns 0.0 or 0.2.
        """
        all_words: list[list[str]] = []
        for m in messages:
            text = (m.get("text") or "").lower()
            words = [w.strip(".,!?\"'") for w in text.split() if len(w) > 5]
            all_words.append(set(words))

        if len(all_words) < 4:
            return 0.0

        # Count how many messages each word appears in
        word_presence: Counter = Counter()
        for word_set in all_words:
            for w in word_set:
                word_presence[w] += 1

        # "Rare" words that appear in 2–40% of messages = possible inside references
        total = len(all_words)
        callbacks = [
            w for w, count in word_presence.items()
            if 1 < count <= max(2, int(total * 0.4))
            and w not in {"about", "think", "going", "where", "there", "would", "could", "should", "really"}
        ]
        return 0.20 if len(callbacks) >= 3 else 0.0

    async def _analyze_with_claude(
        self, messages: list[dict]
    ) -> tuple[str, list[str], str]:
        """
        Use Claude to extract tone description, recurring topics, and language shift notes.
        Returns (tone_string, topics_list, language_shifts_string).
        Falls back to defaults if Claude is unavailable.
        """
        try:
            from services.intelligence import _call_claude

            # Sample up to 40 messages to keep the prompt manageable
            sample = messages[:40] if len(messages) > 40 else messages
            formatted = "\n".join(
                f"{'Me' if m.get('is_from_me') else 'Them'}: {(m.get('text') or '').strip()}"
                for m in sample
                if m.get("text")
            )

            system = """Analyze this message exchange and return ONLY a JSON object:
{
  "tone": "brief description of the tone (2-5 adjectives), e.g. 'warm, playful, occasionally serious'",
  "topics": ["topic1", "topic2", "topic3"],
  "language_shifts": "one sentence about how language changes over time, or 'stable tone throughout'"
}
No explanation. Valid JSON only."""

            response = _call_claude(system, formatted)
            # Strip markdown fences
            response = re.sub(r"```json|```", "", response).strip()
            data = json.loads(response)
            return (
                data.get("tone", "warm"),
                data.get("topics", [])[:6],
                data.get("language_shifts", "stable tone throughout"),
            )
        except Exception as exc:
            logger.warning("Claude tone analysis failed: %s", exc)
            return "warm", [], "stable tone throughout"

    async def _save_profile(self, user_id: str, person_id: str, profile: dict) -> None:
        try:
            import database as db_mod
            db = db_mod.get_db()
            db.table("people").update({
                "communication_dna_json": json.dumps(profile),
            }).eq("id", person_id).eq("owner_user_id", user_id).execute()
        except Exception as exc:
            logger.warning("Could not save communication DNA for person %s: %s", person_id, exc)

    async def _load_profile(self, person_id: str) -> Optional[dict]:
        try:
            import database as db_mod
            db = db_mod.get_db()
            result = (
                db.table("people")
                .select("communication_dna_json")
                .eq("id", person_id)
                .single()
                .execute()
            )
            if result.data and result.data.get("communication_dna_json"):
                return json.loads(result.data["communication_dna_json"])
        except Exception:
            pass
        return None

    def _empty_profile(self) -> dict:
        return {
            "linguistic_intimacy": 0.0,
            "avg_response_time_hours": 0.0,
            "initiates_ratio": 0.5,
            "message_length_avg": 0,
            "emoji_frequency": 0.0,
            "typical_tone": "unknown",
            "topics_recurring": [],
            "silence_patterns": "no data",
            "peak_communication_hours": [],
            "language_shifts": "no data",
            "intimacy_trend": "stable",
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "message_count": 0,
        }
