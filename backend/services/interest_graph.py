"""
services/interest_graph.py — Full interest graph with confidence, recency, and source tracking.

Extends the lightweight services/interests.py with:
  - Multi-source ingestion (messages, calendar, maps, transactions)
  - Confidence scoring (0.0–1.0)
  - Deduplication and merge across sources
  - Trend tracking (seen_count, last_seen_at)

Storage: user_interests table.
  Columns: id, user_id, category, subcategory, value, confidence, source,
           last_seen_at, seen_count, created_at.

Claude is used for structured extraction. Results are cached — if we see
the same value again, we increment seen_count and boost confidence rather
than inserting a duplicate.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Interest categories ────────────────────────────────────────────────────────

CATEGORIES = {
    "music",
    "food",
    "fitness",
    "travel",
    "culture",
    "intellectual",
    "social",
}

# Source → confidence multiplier
SOURCE_CONFIDENCE = {
    "transaction": 0.9,       # paid for it = strong signal
    "calendar": 0.8,          # scheduled it = strong
    "maps": 0.7,              # visited = moderate-strong
    "message": 0.6,           # mentioned = moderate
    "voice_note": 0.65,
    "google_ingestion": 0.55,
    "manual": 1.0,            # user explicitly told us
}

# Keyword → (category, subcategory) hints for fast extraction without Claude
KEYWORD_HINTS: dict[str, tuple[str, str]] = {
    "yoga": ("fitness", "activities"),
    "running": ("fitness", "activities"),
    "gym": ("fitness", "activities"),
    "hiking": ("fitness", "activities"),
    "cycling": ("fitness", "activities"),
    "pilates": ("fitness", "activities"),
    "crossfit": ("fitness", "activities"),
    "sushi": ("food", "cuisines"),
    "pizza": ("food", "cuisines"),
    "indian": ("food", "cuisines"),
    "italian": ("food", "cuisines"),
    "japanese": ("food", "cuisines"),
    "tacos": ("food", "cuisines"),
    "vegan": ("food", "dietary_notes"),
    "vegetarian": ("food", "dietary_notes"),
    "gluten": ("food", "dietary_notes"),
    "jazz": ("music", "genres"),
    "hip-hop": ("music", "genres"),
    "classical": ("music", "genres"),
    "pop": ("music", "genres"),
    "rock": ("music", "genres"),
    "edm": ("music", "genres"),
    "techno": ("music", "genres"),
    "podcast": ("intellectual", "topics"),
    "book": ("culture", "books"),
    "novel": ("culture", "books"),
    "reading": ("culture", "books"),
    "film": ("culture", "films"),
    "movie": ("culture", "films"),
    "show": ("culture", "shows"),
    "series": ("culture", "shows"),
    "travel": ("travel", "travel_style"),
    "trip": ("travel", "destinations_visited"),
    "flight": ("travel", "destinations_visited"),
    "hotel": ("travel", "destinations_visited"),
    "art": ("culture", "art"),
    "museum": ("culture", "art"),
    "meditation": ("fitness", "activities"),
    "therapy": ("social", "activity_preferences"),
    "brunch": ("social", "activity_preferences"),
    "dinner": ("social", "activity_preferences"),
    "coffee": ("social", "activity_preferences"),
}


class InterestGraph:
    """
    Builds and maintains a full interest graph for a user.

    Usage:
        graph = InterestGraph()
        await graph.update_from_message(user_id, "I've been obsessed with jazz lately")
        profile = await graph.get_profile(user_id)
        top = await graph.get_top_interests(user_id, limit=5)
    """

    # ── Public update methods ─────────────────────────────────────────────────

    async def update_from_message(self, user_id: str, message: str) -> list[dict]:
        """Extract interests from a message and upsert into user_interests."""
        signals = await self._extract_from_text(message, source="message")
        return await self._upsert_signals(user_id, signals)

    async def update_from_calendar(
        self, user_id: str, events: list[dict]
    ) -> list[dict]:
        """
        Extract interests from calendar events.
        events: list of {title: str, description: str, location: str}
        """
        combined_text = " ".join(
            f"{e.get('title', '')} {e.get('description', '')} {e.get('location', '')}"
            for e in events
        )
        signals = await self._extract_from_text(combined_text, source="calendar")
        return await self._upsert_signals(user_id, signals)

    async def update_from_maps(
        self, user_id: str, places: list[dict]
    ) -> list[dict]:
        """
        Extract interests from visited places.
        places: list of {name: str, category: str, address: str}
        """
        signals = []
        for place in places:
            cat = (place.get("category") or "").lower()
            name = place.get("name", "")
            for keyword, (interest_cat, subcat) in KEYWORD_HINTS.items():
                if keyword in cat or keyword in name.lower():
                    signals.append({
                        "category": interest_cat,
                        "subcategory": subcat,
                        "value": name or keyword,
                        "confidence": SOURCE_CONFIDENCE["maps"],
                        "source": "maps",
                    })
                    break
        return await self._upsert_signals(user_id, signals)

    async def update_from_transactions(
        self, user_id: str, transactions: list[dict]
    ) -> list[dict]:
        """
        Extract interests from Plaid transactions.
        transactions: list of {name, categories, capability_signal, amount}
        Never used to infer work patterns. Never stored in people graph.
        """
        signals = []
        for txn in transactions:
            signal_type = txn.get("capability_signal")
            if not signal_type:
                continue

            # Map capability_signal → interest category
            if signal_type == "social_food_interest":
                signals.append({
                    "category": "food",
                    "subcategory": "habits",
                    "value": txn.get("merchant_name") or txn.get("name", "restaurant"),
                    "confidence": SOURCE_CONFIDENCE["transaction"],
                    "source": "transaction",
                })
            elif signal_type == "physical_capability":
                signals.append({
                    "category": "fitness",
                    "subcategory": "activities",
                    "value": txn.get("merchant_name") or txn.get("name", "gym"),
                    "confidence": SOURCE_CONFIDENCE["transaction"],
                    "source": "transaction",
                })
            elif signal_type == "intellectual_signal":
                signals.append({
                    "category": "intellectual",
                    "subcategory": "topics",
                    "value": txn.get("merchant_name") or txn.get("name", "books"),
                    "confidence": SOURCE_CONFIDENCE["transaction"],
                    "source": "transaction",
                })
            elif signal_type == "travel_interest":
                signals.append({
                    "category": "travel",
                    "subcategory": "destinations_visited",
                    "value": txn.get("merchant_name") or txn.get("name", "travel"),
                    "confidence": SOURCE_CONFIDENCE["transaction"],
                    "source": "transaction",
                })
            # emotional_capability (mental health) is intentionally excluded here

        return await self._upsert_signals(user_id, signals)

    # ── Profile retrieval ─────────────────────────────────────────────────────

    async def get_profile(self, user_id: str) -> dict:
        """
        Return the full interest profile, organized by category.
        Each category contains its subcategories with values, confidence, and recency.
        """
        rows = await self._load_rows(user_id)
        profile: dict[str, dict] = {cat: {} for cat in CATEGORIES}

        for row in rows:
            cat = row.get("category", "")
            subcat = row.get("subcategory", "")
            if cat not in profile:
                profile[cat] = {}
            if subcat not in profile[cat]:
                profile[cat][subcat] = []
            profile[cat][subcat].append({
                "value": row.get("value"),
                "confidence": row.get("confidence", 0.5),
                "source": row.get("source"),
                "seen_count": row.get("seen_count", 1),
                "last_seen_at": row.get("last_seen_at"),
            })

        # Sort each subcategory list by confidence desc
        for cat in profile:
            for subcat in profile[cat]:
                profile[cat][subcat].sort(key=lambda x: -x.get("confidence", 0))

        return profile

    async def get_top_interests(self, user_id: str, limit: int = 10) -> list[str]:
        """
        Return top interest values ranked by confidence × seen_count.
        Returns plain string values.
        """
        rows = await self._load_rows(user_id)
        scored = []
        for row in rows:
            confidence = row.get("confidence", 0.5)
            seen = row.get("seen_count", 1)
            score = confidence * (1 + 0.1 * seen)
            value = row.get("value", "")
            if value:
                scored.append((value, score))

        scored.sort(key=lambda x: -x[1])
        seen_values: set[str] = set()
        result = []
        for value, _ in scored:
            if value not in seen_values:
                seen_values.add(value)
                result.append(value)
                if len(result) >= limit:
                    break
        return result

    # ── Extraction helpers ────────────────────────────────────────────────────

    async def _extract_from_text(self, text: str, source: str) -> list[dict]:
        """
        Extract interest signals from free text.
        First tries keyword hints (fast), then falls back to Claude (slow but thorough).
        """
        signals = self._extract_with_keywords(text, source)
        if not signals:
            signals = await self._extract_with_claude(text, source)
        return signals

    def _extract_with_keywords(self, text: str, source: str) -> list[dict]:
        """Fast keyword-based extraction without an AI call."""
        text_lower = text.lower()
        signals = []
        seen_keys: set[str] = set()
        for keyword, (cat, subcat) in KEYWORD_HINTS.items():
            if keyword in text_lower and (cat, subcat, keyword) not in seen_keys:
                seen_keys.add((cat, subcat, keyword))
                signals.append({
                    "category": cat,
                    "subcategory": subcat,
                    "value": keyword,
                    "confidence": SOURCE_CONFIDENCE.get(source, 0.5) * 0.85,  # slight discount vs Claude
                    "source": source,
                })
        return signals

    async def _extract_with_claude(self, text: str, source: str) -> list[dict]:
        """Use Claude to extract structured interest signals from text."""
        try:
            from services.intelligence import _call_claude

            system = f"""Extract interest signals from this text. Return a JSON array.
Each item must have:
  "category": one of {sorted(CATEGORIES)},
  "subcategory": e.g. "genres", "cuisines", "activities", "destinations_visited", "books", "films", "shows", "topics", "habits",
  "value": specific string value (e.g. "jazz", "sushi", "running"),
  "confidence": 0.0-1.0 based on how strongly the text signals this interest

If nothing worth capturing, return [].
Return ONLY valid JSON. No explanation."""

            response = _call_claude(system, text[:2000])
            response = re.sub(r"```json|```", "", response).strip()
            items = json.loads(response)
            if not isinstance(items, list):
                return []

            base_confidence = SOURCE_CONFIDENCE.get(source, 0.5)
            signals = []
            for item in items:
                cat = item.get("category", "")
                value = str(item.get("value", "")).strip()
                if cat in CATEGORIES and value:
                    raw_conf = float(item.get("confidence", 0.5))
                    signals.append({
                        "category": cat,
                        "subcategory": item.get("subcategory", "general"),
                        "value": value.lower(),
                        "confidence": round(min(1.0, base_confidence * raw_conf), 2),
                        "source": source,
                    })
            return signals
        except Exception as exc:
            logger.warning("Claude interest extraction failed: %s", exc)
            return []

    # ── DB persistence ────────────────────────────────────────────────────────

    async def _upsert_signals(
        self, user_id: str, signals: list[dict]
    ) -> list[dict]:
        """
        Upsert interest signals. If a matching (user_id, category, subcategory, value)
        already exists, boost confidence and increment seen_count. Otherwise insert.
        Returns the list of upserted/updated records.
        """
        if not signals:
            return []

        results = []
        now = datetime.now(timezone.utc).isoformat()

        try:
            import database as db_mod
            db = db_mod.get_db()

            for signal in signals:
                value = (signal.get("value") or "").strip().lower()
                cat = signal.get("category", "")
                subcat = signal.get("subcategory", "")
                new_conf = signal.get("confidence", 0.5)

                if not value or not cat:
                    continue

                # Check existing
                existing = (
                    db.table("user_interests")
                    .select("id, confidence, seen_count")
                    .eq("user_id", user_id)
                    .eq("category", cat)
                    .eq("subcategory", subcat)
                    .eq("value", value)
                    .execute()
                )

                if existing.data:
                    row = existing.data[0]
                    # Boost confidence slightly (weighted average)
                    old_conf = row.get("confidence", new_conf)
                    seen = row.get("seen_count", 1)
                    merged_conf = round(min(1.0, (old_conf * seen + new_conf) / (seen + 1)), 3)
                    updated = (
                        db.table("user_interests")
                        .update({
                            "confidence": merged_conf,
                            "seen_count": seen + 1,
                            "last_seen_at": now,
                            "source": signal.get("source", "message"),
                        })
                        .eq("id", row["id"])
                        .execute()
                    )
                    results.extend(updated.data or [])
                else:
                    new_row = {
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "category": cat,
                        "subcategory": subcat,
                        "value": value,
                        "confidence": round(new_conf, 3),
                        "source": signal.get("source", "message"),
                        "last_seen_at": now,
                        "seen_count": 1,
                        "created_at": now,
                    }
                    inserted = db.table("user_interests").insert(new_row).execute()
                    results.extend(inserted.data or [new_row])
        except Exception as exc:
            logger.error("_upsert_signals failed for user %s: %s", user_id, exc)

        return results

    async def _load_rows(self, user_id: str) -> list[dict]:
        try:
            import database as db_mod
            db = db_mod.get_db()
            result = (
                db.table("user_interests")
                .select("*")
                .eq("user_id", user_id)
                .order("confidence", desc=True)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.error("_load_rows failed for user %s: %s", user_id, exc)
            return []
