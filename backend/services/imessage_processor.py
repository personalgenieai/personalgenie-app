"""
services/imessage_processor.py — iMessage → People Graph pipeline.

Sits between raw iMessage import (routers/messages.py) and the intelligence layer.
Every conversation passes through WorkFilter before any analysis.

Pipeline per conversation:
  1. WorkFilter.classify each message
  2. Drop work / ambiguous messages
  3. If personal messages remain → analyze_imessage_conversation (intelligence.py)
  4. Run signal_extractor.extract_signals_from_message on each personal message
  5. Store phone_hash on the person record for cross-user matching
  6. Broadcast progress via POST /ingestion/progress/{session_id} if session_id given

Privacy:
  - Raw message text is never stored by this layer (handled inside intelligence.py)
  - Work/ambiguous messages are counted only; content is never surfaced to the analysis layer
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

import httpx

from config import get_settings
from core.ingestion.work_filter import WorkFilter, Label
import database as db

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Phone hashing ─────────────────────────────────────────────────────────────

_DIGIT_STRIP = str.maketrans("", "", " ()-+.")


def hash_phone(phone: str) -> str:
    """
    Normalise a phone number (digits only) then SHA-256 hash it.
    Used to cross-match people across different Genie users without exposing raw numbers.

    Examples:
        hash_phone("+1 (415) 555-1234") == hash_phone("14155551234")
    """
    normalized = phone.translate(_DIGIT_STRIP)
    return hashlib.sha256(normalized.encode()).hexdigest()


# ── Progress broadcaster (fire-and-forget) ────────────────────────────────────

async def _broadcast(
    session_id: str | None,
    source: str,
    stage: str,
    progress: int,
    message: str,
    insight: str | None = None,
    people_found: int = 0,
    user_id: str | None = None,
) -> None:
    """
    POST a progress event to the ingestion router so all WebSocket clients receive it.
    Runs as a fire-and-forget coroutine — never raises.
    """
    if not session_id:
        return
    try:
        payload: dict[str, Any] = {
            "source": source,
            "stage": stage,
            "progress": progress,
            "message": message,
            "insight": insight,
            "people_found": people_found,
            "user_id": user_id,
        }
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{settings.backend_url}/ingestion/progress/{session_id}",
                json=payload,
                timeout=5.0,
            )
    except Exception as exc:
        logger.debug(f"Progress broadcast failed (non-fatal): {exc}")


# ── IMessageProcessor ─────────────────────────────────────────────────────────

class IMessageProcessor:
    """
    Processes a batch of iMessage conversations for one user.

    Each conversation is a dict:
      {
        "contact_name": str,
        "contact_identifier": str,   # phone or email — used for phone_hash
        "messages": [
          {"timestamp": "ISO-str", "text": str, "is_from_me": bool}
        ]
      }
    """

    def __init__(self) -> None:
        self._work_filter = WorkFilter()

    # ── Public API ────────────────────────────────────────────────────────────

    async def process_conversations(
        self,
        user_id: str,
        conversations: list[dict],
        session_id: str | None = None,
    ) -> dict:
        """
        Run the full pipeline for all conversations.

        Returns:
          {
            "processed": int,          # conversations fully analyzed
            "filtered_work": int,      # conversations dropped (work)
            "filtered_ambiguous": int, # conversations dropped (ambiguous)
            "people_updated": int,     # person records touched
          }
        """
        stats = {
            "processed": 0,
            "filtered_work": 0,
            "filtered_ambiguous": 0,
            "people_updated": 0,
        }

        total = len(conversations)
        if total == 0:
            return stats

        # ── Starting milestone ─────────────────────────────────────────────
        await _broadcast(
            session_id, "imessage", "starting", 0,
            "Reading through your messages — give me a moment.",
            user_id=user_id,
        )

        for idx, conv in enumerate(conversations):
            contact_name = conv.get("contact_name", "Unknown")
            contact_identifier = conv.get("contact_identifier", "")
            messages = conv.get("messages", [])

            # Progress percentage: 5% → 95% across all conversations
            pct = 5 + int((idx / total) * 90)
            if idx % max(1, total // 5) == 0:  # broadcast roughly every 20%
                year_hint = ""
                if messages:
                    first_ts = (messages[0].get("timestamp") or "")[:4]
                    if first_ts.isdigit():
                        year_hint = f" from {first_ts}"
                await _broadcast(
                    session_id, "imessage", "reading", pct,
                    f"Reading your messages{year_hint}",
                    user_id=user_id,
                )

            result = await self.process_single_conversation(
                user_id=user_id,
                contact_name=contact_name,
                contact_identifier=contact_identifier,
                messages=messages,
            )

            if result is None:
                # Filtered entirely as work or ambiguous
                # We determine which via a lightweight re-check on the first message
                first_text = messages[0].get("text", "") if messages else ""
                fr = self._work_filter._classify_message({
                    "sender_name": contact_name,
                    "text_snippet": first_text,
                    "group_name": conv.get("group_name", ""),
                })
                if fr and fr.label == Label.WORK:
                    stats["filtered_work"] += 1
                else:
                    stats["filtered_ambiguous"] += 1
            else:
                stats["processed"] += 1
                if result.get("person_updated"):
                    stats["people_updated"] += 1

        # ── Analysing milestone ────────────────────────────────────────────
        await _broadcast(
            session_id, "imessage", "analyzing", 90,
            "Almost there — building your first insights",
            people_found=stats["people_updated"],
            user_id=user_id,
        )

        await _broadcast(
            session_id, "imessage", "complete", 100,
            "Your world is taking shape",
            insight=f"Found {stats['people_updated']} people who matter to you",
            people_found=stats["people_updated"],
            user_id=user_id,
        )

        return stats

    async def process_single_conversation(
        self,
        user_id: str,
        contact_name: str,
        contact_identifier: str,
        messages: list[dict],
        group_name: str = "",
    ) -> dict | None:
        """
        Process one conversation with one contact.
        Returns None if the conversation was fully filtered as work/ambiguous.
        Otherwise returns a result dict.
        """
        if not messages:
            return {}

        personal_messages: list[dict] = []
        filtered_work = 0
        filtered_ambiguous = 0

        for msg in messages:
            text = (msg.get("text") or "").strip()
            if not text:
                continue

            classify_content = {
                "sender_name": contact_name,
                "text_snippet": text[:300],
                "group_name": group_name,
            }

            fr = await self._work_filter.classify(
                content_type="imessage",
                content=classify_content,
                user_id=user_id,
            )

            if fr.label == Label.PERSONAL:
                personal_messages.append(msg)
            elif fr.label == Label.WORK:
                filtered_work += 1
            else:
                filtered_ambiguous += 1

        # If every message had empty text (never hit WorkFilter), return empty result
        total_classified = filtered_work + filtered_ambiguous + len(personal_messages)
        if total_classified == 0:
            return {}

        # If everything got filtered by WorkFilter, skip this conversation
        if not personal_messages:
            logger.debug(
                f"Conversation with {contact_name} fully filtered "
                f"(work={filtered_work}, ambiguous={filtered_ambiguous})"
            )
            return None

        result: dict[str, Any] = {
            "contact_name": contact_name,
            "personal_message_count": len(personal_messages),
            "filtered_work": filtered_work,
            "filtered_ambiguous": filtered_ambiguous,
            "person_updated": False,
        }

        # ── Intelligence analysis ──────────────────────────────────────────
        try:
            from services.intelligence import analyze_imessage_conversation
            analysis = analyze_imessage_conversation(
                user_id=user_id,
                contact_name=contact_name,
                contact_identifier=contact_identifier,
                messages=personal_messages,
            )
            result["analysis"] = analysis
            result["person_updated"] = bool(analysis)
        except Exception as exc:
            logger.error(f"Intelligence analysis failed for {contact_name}: {exc}")

        # ── Phone hash — store on person record for cross-user matching ───
        if contact_identifier:
            try:
                phone_hash = hash_phone(contact_identifier)
                people = db.get_people_for_user(user_id)
                person = next(
                    (
                        p for p in people
                        if contact_name.lower() in p["name"].lower()
                        or p["name"].lower() in contact_name.lower()
                        or contact_identifier in (p.get("phone") or "")
                    ),
                    None,
                )
                if person:
                    db.get_db().table("people").update(
                        {"phone_hash": phone_hash}
                    ).eq("id", person["id"]).execute()
            except Exception as exc:
                logger.warning(f"phone_hash update failed for {contact_name}: {exc}")

        # ── Signal extraction (fire-and-forget) ───────────────────────────
        try:
            from services.signal_extractor import extract_signals_from_message
            user_row = db.get_user_by_id(user_id)
            user_name = user_row.get("name", "") if user_row else ""

            for msg in personal_messages:
                text = (msg.get("text") or "").strip()
                if len(text) > 30:
                    asyncio.create_task(
                        extract_signals_from_message(
                            source_user_id=user_id,
                            message_text=text,
                            participants=[user_name, contact_name],
                        )
                    )
        except Exception as exc:
            logger.warning(f"Signal extraction setup failed for {contact_name}: {exc}")

        return result
