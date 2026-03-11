"""
PersonalGenie Mac Companion — local HTTP server.

Runs on port 5001. On startup it registers its LAN IP with the Railway backend
so the iOS app can discover and call it over local WiFi.

Endpoints:
  GET  /health                 — ping
  GET  /count?phone=+1xxx      — fast message count for a contact
  POST /analyze                — read messages + Claude analysis (takes ~60s)

Requires:
  - Full Disk Access for Terminal in System Settings → Privacy & Security
  - ANTHROPIC_API_KEY in environment or .env file
  - BACKEND_URL in environment (defaults to Railway ngrok URL)
"""
import os
import socket
import json
import logging

import anthropic
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import uvicorn

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger("mac-companion")

PORT = int(os.getenv("MAC_COMPANION_PORT", "5001"))
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://marty-unfocusing-latoya.ngrok-free.dev",
)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

app = FastAPI(title="PersonalGenie Mac Companion", version="1.0.0")


# ── Startup: register with backend ────────────────────────────────────────────

def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


@app.on_event("startup")
def register_with_backend():
    lan_ip = get_lan_ip()
    mac_url = f"http://{lan_ip}:{PORT}"
    try:
        resp = requests.post(
            f"{BACKEND_URL}/mac/register",
            json={"url": mac_url},
            timeout=5,
        )
        if resp.ok:
            log.info(f"Registered with backend as {mac_url}")
        else:
            log.warning(f"Backend registration returned {resp.status_code}: {resp.text}")
    except Exception as e:
        log.warning(f"Could not register with backend: {e}")
    log.info(f"Mac companion running at {mac_url}")
    log.info("Waiting for iOS app to connect...")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "PersonalGenie Mac Companion"}


@app.get("/count")
def count_messages_endpoint(phone: str = Query(..., description="E.164 phone number")):
    from chat_reader import count_messages
    count = count_messages(phone)
    return {"count": count, "phone": phone}


class BatchCountRequest(BaseModel):
    phones: list[str]


@app.post("/batch-count")
def batch_count_endpoint(body: BatchCountRequest):
    """
    Count messages for many phones at once. Used to rank contacts by closeness.
    Returns { counts: { phone: count } }
    """
    from chat_reader import batch_count_messages
    log.info(f"Batch counting {len(body.phones)} phones...")
    counts = batch_count_messages(body.phones)
    log.info(f"Batch count done. Non-zero: {sum(1 for v in counts.values() if v > 0)}")
    return {"counts": counts}


class AnalyzeRequest(BaseModel):
    contact_name: str
    contact_phone: str
    user_id: str | None = None


@app.post("/analyze")
def analyze(body: AnalyzeRequest):
    """
    Read iMessages with the contact and run Claude analysis.
    Returns RelationshipInsights JSON. Takes ~60 seconds.
    """
    from chat_reader import get_messages

    log.info(f"Starting analysis for {body.contact_name} ({body.contact_phone})")
    messages, total = get_messages(body.contact_phone)

    if not messages:
        log.warning(f"No messages found for {body.contact_phone}")
        raise HTTPException(
            status_code=404,
            detail=f"No iMessages found for {body.contact_name}. "
                   "Make sure Full Disk Access is enabled for Terminal.",
        )

    log.info(f"Found {total} total messages, sending {len(messages)} to Claude...")
    result = _analyze_with_claude(body.contact_name, messages, total)
    result["message_count"] = total
    log.info(f"Analysis complete for {body.contact_name}")
    return result


# ── Claude analysis ───────────────────────────────────────────────────────────

def _build_transcript(contact_name: str, messages: list[dict]) -> str:
    """Build readable conversation transcript from messages."""
    lines = []
    for m in messages:
        speaker = "Me" if m["is_from_me"] else contact_name
        lines.append(f"{speaker}: {m['text']}")
    return "\n".join(lines)


def _analyze_with_claude(contact_name: str, messages: list[dict], total: int) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Sample strategically: oldest 200 + middle 400 + most recent 1400 messages
    # This gives Claude a sense of the full arc, not just recent messages
    sampled = _sample_messages(messages)
    conversation = _build_transcript(contact_name, sampled)

    # Trim to safe context size
    MAX_CHARS = 180_000
    trimmed_note = ""
    if len(conversation) > MAX_CHARS:
        conversation = conversation[-MAX_CHARS:]
        trimmed_note = f"(Showing a representative sample of {len(sampled):,} messages)"
    else:
        trimmed_note = f"(Showing {len(sampled):,} of {total:,} messages — oldest, middle, and most recent)"

    prompt = f"""You are reading a real iMessage conversation between me and {contact_name} to surface the truth of this relationship.

Total message history: {total:,} messages
{trimmed_note}

<conversation>
{conversation}
</conversation>

Your job: find what is SPECIFIC and REAL in these messages. Do NOT be generic. Do NOT give advice that could apply to any relationship.

Return a JSON object with exactly these fields:

{{
  "key_memory": "The single most vivid, specific thing you noticed — a scene, a running joke, a moment of tension or tenderness, a phrase they repeat, something that captures the essence of who these two people are to each other. Should feel like something only they would recognize. 2-3 sentences, written as if speaking directly to me ('You two always...', 'There's a moment where...', 'You never say it outright, but...'). This is the aha moment.",
  "summary": "2-3 honest sentences about what this relationship actually is — the unspoken dynamic, what each person seems to need, the pattern that runs through everything",
  "message_count": {total},
  "who_initiates": "user" or "them" or "equal" or "unknown",
  "memories": [
    "a specific memory from the messages — a real exchange, a real moment, specific enough to be unambiguous",
    "a second specific memory or running pattern you spotted",
    "a third — could be something they avoid saying, something they always say, or a recurring topic"
  ],
  "relationship_score": a number 1-10 based on warmth, frequency, reciprocity, and depth you observed,
  "tip": "one specific action based on what you actually read — reference something real from the messages, not generic relationship advice"
}}

Return ONLY the raw JSON object. No markdown fences, no explanation, no preamble."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Strip any accidental markdown fences
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break

    try:
        result = json.loads(raw)
        # Ensure key_memory exists (backwards compat)
        if "key_memory" not in result:
            result["key_memory"] = result.get("memories", [""])[0] if result.get("memories") else ""
        return result
    except json.JSONDecodeError as e:
        log.warning(f"Claude returned non-JSON ({e}): {raw[:200]}")
        return {
            "key_memory": "",
            "summary": f"A relationship with {contact_name} spanning {total:,} messages.",
            "message_count": total,
            "who_initiates": "unknown",
            "memories": [],
            "relationship_score": None,
            "tip": "",
        }


def _sample_messages(messages: list[dict]) -> list[dict]:
    """
    Return a representative sample: oldest 200 + middle 400 + most recent 1400.
    Gives Claude a view of the full arc of the relationship.
    """
    n = len(messages)
    if n <= 2000:
        return messages

    oldest = messages[:200]
    mid_start = n // 2 - 200
    middle = messages[mid_start:mid_start + 400]
    recent = messages[-1400:]

    # Deduplicate while preserving order
    seen = set()
    result = []
    for m in oldest + middle + recent:
        key = (m["text"], m["timestamp"])
        if key not in seen:
            seen.add(key)
            result.append(m)
    return result


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set. Add it to mac-companion/.env")
        exit(1)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
