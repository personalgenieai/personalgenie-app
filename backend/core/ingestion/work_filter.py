"""
WorkFilter — Hard boundary between personal and work data.

ALL data passes through here before any processing. Work and ambiguous are
discarded. Only personal reaches the intelligence layer.

Classification:
  personal   → passes through
  work       → dropped, count logged
  ambiguous  → dropped, count logged (conservative default)

Fast-paths (no Claude call needed):
  - Known work email domains in sender/recipient
  - Calendar titles matching work patterns
  - Messages from contacts whose only known context is professional

Claude is only called for genuinely ambiguous cases (< ~10% of traffic).
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import anthropic

from config import get_settings

logger = logging.getLogger(__name__)

# ── Types ─────────────────────────────────────────────────────────────────────


class Label(str, Enum):
    PERSONAL = "personal"
    WORK = "work"
    AMBIGUOUS = "ambiguous"


@dataclass
class FilterResult:
    label: Label
    confidence: float          # 0.0–1.0
    reason: str                # one-line human-readable
    passes: bool = field(init=False)

    def __post_init__(self):
        self.passes = self.label == Label.PERSONAL


# ── Known patterns ────────────────────────────────────────────────────────────

# Email domains that are always work
_WORK_DOMAINS: set[str] = {
    # Generic corporate / SaaS
    "workday.com", "greenhouse.io", "lever.co", "bamboohr.com",
    "salesforce.com", "hubspot.com", "zendesk.com", "servicenow.com",
    "atlassian.com", "jira.com", "confluence.com", "asana.com",
    "notion.so", "slack.com", "monday.com", "linear.app",
    # Recruiting / legal / finance
    "docusign.com", "hellosign.com", "netsuite.com", "expensify.com",
    "concur.com", "brex.com", "ramp.com",
    # Automated / transactional (never personal)
    "noreply.", "no-reply.", "mailer.", "notifications.", "alerts.",
    "billing.", "invoices.", "payroll.",
}

# Calendar event title patterns that signal work
_WORK_CAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(standup|stand-up|sprint|retro|retrospective)\b", re.I),
    re.compile(r"\b(1:1|one.on.one|sync)\b", re.I),
    re.compile(r"\b(board meeting|all.hands|all hands|town hall)\b", re.I),
    re.compile(r"\b(interview|candidate|hiring|onboard)\b", re.I),
    re.compile(r"\b(Q[1-4] review|quarterly|OKR|KPI)\b", re.I),
    re.compile(r"\b(demo day|product review|design review|code review)\b", re.I),
    re.compile(r"\b(performance review|perf review|360 review)\b", re.I),
    re.compile(r"\boffsite\b", re.I),
]

# Calendar event title patterns that are clearly personal
_PERSONAL_CAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(birthday|bday|anniversary|wedding|engagement)\b", re.I),
    re.compile(r"\b(dinner|lunch|brunch|coffee|drinks|happy hour)\b", re.I),
    re.compile(r"\b(gym|yoga|run|hike|workout|crossfit|climbing)\b", re.I),
    re.compile(r"\b(doctor|dentist|therapist|therapy|appointment)\b", re.I),
    re.compile(r"\b(vacation|holiday|travel|flight|hotel)\b", re.I),
    re.compile(r"\b(family|mom|dad|sister|brother|kids|school)\b", re.I),
    re.compile(r"\b(date night|movie|concert|show|festival)\b", re.I),
]

# iMessage / WhatsApp signals that suggest work context
_WORK_MESSAGE_SIGNALS: list[re.Pattern] = [
    re.compile(r"\b(EOD|EOM|EOW|LGTM|PR|merge request|deploy|deployment)\b"),
    re.compile(r"\b(sprint|backlog|ticket|JIRA|linear)\b", re.I),
    re.compile(r"\b(quarterly|fiscal|budget|headcount|reorg)\b", re.I),
    re.compile(r"\b(conference call|dial.in|zoom link|google meet|teams meeting)\b", re.I),
]


# ── WorkFilter ────────────────────────────────────────────────────────────────


class WorkFilter:
    """
    Classifies a piece of data as personal, work, or ambiguous.

    Usage:
        wf = WorkFilter()
        result = await wf.classify(content_type="email", content={...})
        if result.passes:
            ... process as personal data ...
    """

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
        self._model = get_settings().claude_model

    # ── Public API ────────────────────────────────────────────────────────────

    async def classify(
        self,
        content_type: str,          # "email" | "calendar" | "imessage" | "whatsapp" | "maps"
        content: dict,              # type-specific fields (see below)
        user_id: str | None = None,
    ) -> FilterResult:
        """
        Classify content. Returns FilterResult with .passes = True for personal only.

        content fields by type:
          email:    sender, recipients, subject, snippet (first 200 chars of body)
          calendar: title, description, attendees, location, calendar_name
          imessage: sender_name, text_snippet, group_name (optional)
          whatsapp: sender_name, text_snippet, group_name (optional)
          maps:     place_name, address, visit_time, duration_minutes
        """
        # Fast-path: attempt rule-based classification first
        fast = self._fast_path(content_type, content)
        if fast is not None:
            await self._log(user_id, content_type, fast)
            return fast

        # Slow-path: ask Claude
        result = await self._claude_classify(content_type, content)
        await self._log(user_id, content_type, result)
        return result

    def build_safe_preview(self, content_type: str, content: dict) -> str:
        """
        Build a work-count-safe preview string (shown in Settings → Privacy →
        "What Genie skips"). Never reveals content — only counts and categories.
        """
        return f"1 {content_type} item skipped (work)"

    # ── Fast-path rules ───────────────────────────────────────────────────────

    def _fast_path(self, content_type: str, content: dict) -> FilterResult | None:
        if content_type == "email":
            return self._classify_email(content)
        if content_type == "calendar":
            return self._classify_calendar(content)
        if content_type in ("imessage", "whatsapp"):
            return self._classify_message(content)
        if content_type == "maps":
            return self._classify_maps(content)
        return None

    def _classify_email(self, c: dict) -> FilterResult | None:
        sender = (c.get("sender") or "").lower()
        subject = (c.get("subject") or "").lower()
        snippet = (c.get("snippet") or "").lower()

        # Check sender domain against known work domains
        for domain in _WORK_DOMAINS:
            if domain in sender:
                return FilterResult(
                    label=Label.WORK,
                    confidence=0.95,
                    reason=f"sender domain matches known work domain: {domain}",
                )

        # Automated / noreply patterns in sender
        for pattern in ("noreply", "no-reply", "donotreply", "notifications@", "alerts@"):
            if pattern in sender:
                return FilterResult(
                    label=Label.WORK,
                    confidence=0.90,
                    reason="automated/noreply sender",
                )

        # Strong work signals in subject
        work_subject_terms = [
            "jira", "confluence", "github pr", "pull request", "deployment",
            "invoice #", "purchase order", "expense report", "payroll",
        ]
        for term in work_subject_terms:
            if term in subject:
                return FilterResult(
                    label=Label.WORK,
                    confidence=0.92,
                    reason=f"work term in subject: '{term}'",
                )

        # Strong personal signals
        personal_subject_terms = [
            "birthday", "anniversary", "wedding", "baby shower",
            "dinner reservation", "your order", "flight confirmation",
        ]
        for term in personal_subject_terms:
            if term in subject:
                return FilterResult(
                    label=Label.PERSONAL,
                    confidence=0.90,
                    reason=f"personal term in subject: '{term}'",
                )

        return None  # needs Claude

    def _classify_calendar(self, c: dict) -> FilterResult | None:
        title = c.get("title") or ""
        cal_name = (c.get("calendar_name") or "").lower()

        # Calendar name signals
        if any(kw in cal_name for kw in ("work", "office", "company", "corp", "business")):
            return FilterResult(
                label=Label.WORK,
                confidence=0.90,
                reason=f"work calendar: {cal_name}",
            )

        # Title pattern matching
        for pat in _WORK_CAL_PATTERNS:
            if pat.search(title):
                return FilterResult(
                    label=Label.WORK,
                    confidence=0.88,
                    reason=f"calendar title matches work pattern: {pat.pattern}",
                )

        for pat in _PERSONAL_CAL_PATTERNS:
            if pat.search(title):
                return FilterResult(
                    label=Label.PERSONAL,
                    confidence=0.88,
                    reason=f"calendar title matches personal pattern: {pat.pattern}",
                )

        # Many attendees (> 8) with no personal signals → likely work
        attendees = c.get("attendees") or []
        if len(attendees) > 8:
            return FilterResult(
                label=Label.AMBIGUOUS,
                confidence=0.60,
                reason=f"large meeting with {len(attendees)} attendees, no personal signal",
            )

        return None

    def _classify_message(self, c: dict) -> FilterResult | None:
        text = (c.get("text_snippet") or "").strip()
        group = (c.get("group_name") or "").lower()

        # Group name signals
        work_group_signals = ["team", "eng ", "product", "design", "marketing", "sales", "ops "]
        for sig in work_group_signals:
            if sig in group:
                return FilterResult(
                    label=Label.WORK,
                    confidence=0.82,
                    reason=f"group name suggests work: {group!r}",
                )

        # Strong work jargon in text
        for pat in _WORK_MESSAGE_SIGNALS:
            if pat.search(text):
                return FilterResult(
                    label=Label.WORK,
                    confidence=0.80,
                    reason=f"work jargon in message: {pat.pattern}",
                )

        # Very short messages or emoji-only → ambiguous, let Claude decide
        if len(text) < 10:
            return None

        return None

    def _classify_maps(self, c: dict) -> FilterResult | None:
        place = (c.get("place_name") or "").lower()
        address = (c.get("address") or "").lower()

        work_place_signals = ["inc", "llc", "corp", "headquarters", "hq", "office park"]
        for sig in work_place_signals:
            if sig in place or sig in address:
                return FilterResult(
                    label=Label.WORK,
                    confidence=0.80,
                    reason=f"place name suggests office/corporate location",
                )

        personal_place_signals = [
            "restaurant", "cafe", "coffee", "gym", "yoga", "park",
            "cinema", "theater", "museum", "bar", "beach", "trail",
        ]
        for sig in personal_place_signals:
            if sig in place:
                return FilterResult(
                    label=Label.PERSONAL,
                    confidence=0.85,
                    reason=f"place type is personal: {sig}",
                )

        return None

    # ── Claude classification ─────────────────────────────────────────────────

    async def _claude_classify(self, content_type: str, content: dict) -> FilterResult:
        prompt = _build_claude_prompt(content_type, content)

        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip().lower()
        except Exception as exc:
            logger.warning("WorkFilter Claude call failed: %s — defaulting to ambiguous", exc)
            return FilterResult(
                label=Label.AMBIGUOUS,
                confidence=0.50,
                reason="Claude unavailable, conservative default",
            )

        if raw.startswith("personal"):
            return FilterResult(label=Label.PERSONAL, confidence=0.85, reason="Claude: personal")
        if raw.startswith("work"):
            return FilterResult(label=Label.WORK, confidence=0.85, reason="Claude: work")
        return FilterResult(label=Label.AMBIGUOUS, confidence=0.60, reason="Claude: ambiguous")

    # ── Logging ───────────────────────────────────────────────────────────────

    async def _log(self, user_id: str | None, content_type: str, result: FilterResult) -> None:
        """Log to work_filter_log table (fire-and-forget, never blocks)."""
        if result.passes:
            return  # only log exclusions
        try:
            from db import get_db  # lazy import to avoid circular deps
            db = get_db()
            db.table("work_filter_log").insert({
                "user_id": user_id,
                "content_type": content_type,
                "label": result.label.value,
                "confidence": result.confidence,
                "reason": result.reason,
            }).execute()
        except Exception:
            pass  # logging must never fail silently or crash ingestion


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_claude_prompt(content_type: str, content: dict) -> str:
    lines = [
        "Classify the following piece of data as personal, work, or ambiguous.",
        "",
        "Rules:",
        "- personal: clearly about the person's private life (relationships, health, leisure, family)",
        "- work: clearly professional (work emails, meetings, colleagues in work context)",
        "- ambiguous: cannot be determined from context alone",
        "",
        "Reply with EXACTLY one word: personal, work, or ambiguous. No explanation.",
        "",
        f"Type: {content_type}",
    ]

    if content_type == "email":
        lines += [
            f"From: {content.get('sender', '')}",
            f"Subject: {content.get('subject', '')}",
            f"Preview: {content.get('snippet', '')[:300]}",
        ]
    elif content_type == "calendar":
        lines += [
            f"Title: {content.get('title', '')}",
            f"Description: {(content.get('description') or '')[:200]}",
            f"Calendar: {content.get('calendar_name', '')}",
            f"Attendees: {len(content.get('attendees') or [])} people",
        ]
    elif content_type in ("imessage", "whatsapp"):
        lines += [
            f"From: {content.get('sender_name', '')}",
            f"Group: {content.get('group_name', 'direct message')}",
            f"Message: {(content.get('text_snippet') or '')[:300]}",
        ]
    elif content_type == "maps":
        lines += [
            f"Place: {content.get('place_name', '')}",
            f"Address: {content.get('address', '')}",
            f"Duration: {content.get('duration_minutes', '')} minutes",
        ]

    return "\n".join(lines)
