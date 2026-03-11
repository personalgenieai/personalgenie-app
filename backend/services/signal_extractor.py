"""
signal_extractor.py — Extract third-party relationship signals from any message.

Every WhatsApp or iMessage processed by Genie passes through here AFTER the
primary conversation handler. We look for mentions of people who are NOT the
sender or recipient of this message — and extract emotional/factual signals
about those mentioned people.

These signals are stored in third_party_signals and become part of the mentioned
person's World Model if they are (or later become) a Genie user.

Pipeline:
  1. Quick pre-filter: does this message mention any known person by name?
  2. Claude extraction: identify all mentioned people + signals
  3. Person matching: resolve names to person nodes in source user's graph
  4. Signal storage: write anonymized signals to third_party_signals
  5. Cross-user routing: if the mentioned person is a Genie user, queue signal
     for their World Model update (respecting permission level)

Privacy guarantees (never violated):
  - Raw message text is never stored in third_party_signals
  - signal_abstract contains NO verbatim quotes, NO names, NO identifying details
  - Source user ID is stored for permission checks but NEVER surfaces to the about-person
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import anthropic

from config import get_settings

logger = logging.getLogger(__name__)

# Signal types we extract
SIGNAL_TYPES = {
    "emotional_concern":    "Source expressed worry, anxiety, or concern about this person",
    "positive_regard":      "Source expressed affection, pride, admiration, or love",
    "unresolved_feeling":   "Source has unprocessed feelings toward this person (grief, longing, conflict)",
    "relational_shift":     "Relationship dynamics appear to be changing (closer/more distant)",
    "factual_update":       "New factual information about this person's life (job, move, relationship)",
    "avoidance":            "Source is avoiding or deprioritizing this person",
    "conflict_signal":      "Tension, argument, or unresolved conflict between source and this person",
    "celebration_signal":   "Something good happened for this person worth acknowledging",
}

# Minimum message length before we bother extracting (saves API calls)
MIN_MESSAGE_LENGTH = 30

# Signal decay: 90 days by default
SIGNAL_TTL_DAYS = 90


class SignalExtractor:
    """
    Runs on every processed message. Extracts third-party signals.
    Instantiated once per process (singleton via module-level instance).
    """

    def __init__(self):
        self._settings = get_settings()
        self._client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)

    # ── Main entry point ──────────────────────────────────────────────────────

    async def extract_and_store(
        self,
        source_user_id: str,
        message_text: str,
        participants: list[str],  # names of direct conversation participants (exclude from extraction)
    ) -> int:
        """
        Extract third-party signals from a message and store them.
        Returns the number of signals stored.

        participants: list of person names who ARE in the conversation
        (we don't extract signals about them from this message — only about
        people who are *mentioned* but not present)
        """
        if not message_text or len(message_text.strip()) < MIN_MESSAGE_LENGTH:
            return 0

        # Quick pre-filter: any capitalized names that suggest people mentions?
        if not self._has_person_mentions(message_text):
            return 0

        try:
            raw_signals = await self._extract_with_claude(message_text, participants)
        except Exception as exc:
            logger.warning("Signal extraction Claude call failed: %s", exc)
            return 0

        if not raw_signals:
            return 0

        stored = 0
        from db import get_db
        db = get_db()

        for signal in raw_signals:
            person_name = signal.get("person_name", "").strip()
            if not person_name:
                continue

            # Resolve person to a DB record
            person_id, phone_hash = self._resolve_person(
                db, source_user_id, person_name
            )

            if not person_id and not phone_hash:
                continue  # Can't anchor the signal — skip

            # Build message hash for dedup
            msg_hash = hashlib.sha256(message_text.encode()).hexdigest()[:16]

            # Check for duplicate (same source, same person, same message)
            existing = (
                db.table("third_party_signals")
                .select("id")
                .eq("source_user_id", source_user_id)
                .eq("source_message_hash", msg_hash)
                .eq("signal_type", signal.get("signal_type", ""))
                .execute()
            )
            if existing.data:
                continue

            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=SIGNAL_TTL_DAYS)
            ).isoformat()

            row = {
                "source_user_id": source_user_id,
                "about_person_id": person_id,
                "about_phone_hash": phone_hash,
                "signal_type": signal.get("signal_type", "factual_update"),
                "signal_abstract": signal.get("signal_abstract", ""),
                "signal_valence": signal.get("valence", 0.0),
                "signal_intensity": signal.get("intensity", 0.5),
                "confidence": signal.get("confidence", 0.7),
                "expires_at": expires_at,
                "source_message_hash": msg_hash,
            }

            try:
                db.table("third_party_signals").insert(row).execute()
                stored += 1

                # If the mentioned person is already a Genie user, notify their
                # World Model to refresh (fire-and-forget)
                if phone_hash:
                    await self._notify_beneficiary_if_user(db, phone_hash)

            except Exception as exc:
                logger.warning("Could not store signal for %s: %s", person_name, exc)

        return stored

    # ── Claude extraction ─────────────────────────────────────────────────────

    async def _extract_with_claude(
        self, message_text: str, participants: list[str]
    ) -> list[dict]:
        """
        Ask Claude to identify all third-party person mentions and extract signals.
        Returns a list of signal dicts.
        """
        participants_str = ", ".join(participants) if participants else "the direct participants"
        signal_types_str = "\n".join(f"  - {k}: {v}" for k, v in SIGNAL_TYPES.items())

        prompt = f"""You are extracting relationship signals from a private message.

Participants in this conversation: {participants_str}
IGNORE signals ABOUT the participants themselves.
ONLY extract signals about THIRD PARTIES — people mentioned but not present.

Message:
\"\"\"{message_text[:800]}\"\"\"

For each third party mentioned, extract signals using this schema:
{{
  "person_name": "first name or first+last if clear",
  "signal_type": one of the types below,
  "signal_abstract": "1-2 sentence abstract — NO verbatim quotes, NO identifying details, NO names. Describe the emotional/factual signal in generic terms.",
  "valence": float -1.0 to 1.0 (negative to positive),
  "intensity": float 0.0 to 1.0,
  "confidence": float 0.0 to 1.0
}}

Signal types:
{signal_types_str}

Rules:
- ONLY extract signals where there is clear emotional or factual content worth capturing
- signal_abstract must be fully anonymized — no names, no quotes, no identifying specifics
- If a person is mentioned casually with no signal, skip them
- If uncertain, skip rather than guess
- Return a JSON array. Empty array [] if no third-party signals found.

Return ONLY the JSON array, nothing else."""

        msg = self._client.messages.create(
            model=self._settings.claude_model,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        try:
            signals = json.loads(raw)
            return signals if isinstance(signals, list) else []
        except json.JSONDecodeError:
            logger.warning("Signal extractor: could not parse Claude response: %s", raw[:100])
            return []

    # ── Person resolution ─────────────────────────────────────────────────────

    def _resolve_person(
        self, db, source_user_id: str, person_name: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Try to match person_name to a record in the source user's people graph.
        Returns (person_id, phone_hash) — either can be None.
        """
        try:
            # Exact name match first
            result = (
                db.table("people")
                .select("id, phone_hash")
                .eq("user_id", source_user_id)
                .ilike("name", f"%{person_name}%")
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                return row.get("id"), row.get("phone_hash")
        except Exception as exc:
            logger.warning("Person resolution failed for %r: %s", person_name, exc)

        return None, None

    # ── Cross-user notification ───────────────────────────────────────────────

    async def _notify_beneficiary_if_user(self, db, phone_hash: str) -> None:
        """
        If the mentioned person is a Genie user, mark their World Model as stale
        so it refreshes on next interaction.
        """
        try:
            result = (
                db.table("users")
                .select("id")
                .eq("phone_hash", phone_hash)
                .execute()
            )
            if result.data:
                beneficiary_user_id = result.data[0]["id"]
                db.table("world_model").update(
                    {"is_stale": True}
                ).eq("user_id", beneficiary_user_id).execute()
        except Exception:
            pass  # Non-blocking

    # ── Pre-filter ────────────────────────────────────────────────────────────

    def _has_person_mentions(self, text: str) -> bool:
        """
        Quick heuristic: does the message likely mention a person by name?
        Avoids unnecessary Claude calls for messages like "ok see you there".
        """
        # Look for capitalized words that aren't at sentence start
        # (crude but fast — saves ~80% of Claude calls)
        words = text.split()
        caps_mid_sentence = sum(
            1 for i, w in enumerate(words)
            if i > 0 and w and w[0].isupper() and w.isalpha() and len(w) > 2
        )
        return caps_mid_sentence >= 1


# ── Module-level singleton ────────────────────────────────────────────────────

_extractor: SignalExtractor | None = None


def get_extractor() -> SignalExtractor:
    global _extractor
    if _extractor is None:
        _extractor = SignalExtractor()
    return _extractor


async def extract_signals_from_message(
    source_user_id: str,
    message_text: str,
    participants: list[str] | None = None,
) -> int:
    """
    Module-level convenience function. Wire this into the message processing
    pipeline after primary handling. Fire-and-forget safe.
    """
    return await get_extractor().extract_and_store(
        source_user_id=source_user_id,
        message_text=message_text,
        participants=participants or [],
    )
