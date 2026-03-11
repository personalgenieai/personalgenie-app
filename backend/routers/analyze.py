"""
analyze.py — Relationship analysis router.
POST /analyze/relationship
Takes a pasted iMessage conversation + contact info → Claude → relationship insights JSON.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import anthropic
import json
import os

router = APIRouter(prefix="/analyze", tags=["analyze"])

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


class RelationshipRequest(BaseModel):
    user_id: str
    contact_name: str
    contact_phone: Optional[str] = None
    conversation_text: str


class RelationshipInsights(BaseModel):
    summary: str
    message_count: Optional[int] = None
    who_initiates: str = "unknown"
    memories: list[str] = []
    relationship_score: Optional[float] = None
    tip: str


@router.post("/relationship", response_model=RelationshipInsights)
async def analyze_relationship(req: RelationshipRequest):
    prompt = f"""You are analyzing a personal relationship for someone using Personal Genie.

Contact name: {req.contact_name}

Conversation history (copied from iMessage — may be incomplete or lack sender labels):
---
{req.conversation_text[:8000]}
---

Analyze this conversation and return ONLY valid JSON with these exact fields:
{{
  "summary": "2-3 sentence warm, specific description of this relationship based on what you can see in the messages",
  "message_count": <integer estimate of total messages in the conversation, or null if unclear>,
  "who_initiates": "<'user' if the person who copied this tends to message first, 'them' if the contact does, 'equal' if balanced, 'unknown' if unclear>",
  "memories": ["specific memory or moment from the conversation 1", "specific memory 2", "specific memory 3"],
  "relationship_score": <float 1.0-10.0 representing closeness/depth based on conversation quality, or null>,
  "tip": "One very specific, actionable tip to improve or deepen this relationship — based on actual patterns you noticed. Not generic advice."
}}

Rules:
- memories must be specific things mentioned in the conversation, not generic
- tip must reference something specific from the conversation
- if the conversation is too short or unclear, still return valid JSON with your best inference
- return ONLY the JSON object, no other text"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback
        data = {
            "summary": f"Your relationship with {req.contact_name} is meaningful. I wasn't able to parse the full conversation but I can tell you care about this person.",
            "message_count": None,
            "who_initiates": "unknown",
            "memories": [],
            "relationship_score": None,
            "tip": "Reach out to them today with something specific you've been thinking about them.",
        }

    return RelationshipInsights(
        summary=data.get("summary", ""),
        message_count=data.get("message_count"),
        who_initiates=data.get("who_initiates", "unknown"),
        memories=data.get("memories", []),
        relationship_score=data.get("relationship_score"),
        tip=data.get("tip", ""),
    )
