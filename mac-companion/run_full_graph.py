"""
Full contact relationship graph — batch count all contacts,
analyze top N by message count, build initial vault data.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import sqlite3
import anthropic
from chat_reader import batch_count_messages, get_messages, normalize_variants

client = anthropic.Anthropic()
CHAT_DB = os.path.expanduser("~/Library/Messages/chat.db")
TOP_N = 15   # analyze top N by message count
MIN_MESSAGES = 50  # skip anyone with fewer than this

def get_all_handles():
    """Get all unique phone/email handles from chat.db."""
    conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
    c = conn.cursor()
    c.execute("SELECT id FROM handle WHERE id NOT LIKE '%@%' AND length(id) >= 7")
    phones = [r[0] for r in c.fetchall()]
    conn.close()
    return phones

def sample(messages, n_oldest=100, n_mid=200, n_recent=800):
    total = len(messages)
    if total <= n_oldest + n_mid + n_recent:
        return messages
    oldest = messages[:n_oldest]
    mid_s  = total // 2 - n_mid // 2
    middle = messages[mid_s:mid_s + n_mid]
    recent = messages[-n_recent:]
    seen, result = set(), []
    for m in oldest + middle + recent:
        k = (m["text"], m["timestamp"])
        if k not in seen:
            seen.add(k)
            result.append(m)
    return result

def build_transcript(name, messages, max_chars=40000):
    lines = []
    for m in messages:
        speaker = "Leo" if m["is_from_me"] else name
        lines.append(f"{speaker}: {m['text']}")
    t = "\n".join(lines)
    return t[-max_chars:] if len(t) > max_chars else t

def analyze_contact(name, phone, total, messages):
    transcript = build_transcript(name, sample(messages))
    prompt = f"""Analyze this iMessage conversation between Leo and {name} ({total:,} total messages).

<conversation>
{transcript}
</conversation>

Return JSON with exactly these fields:
{{
  "relationship_type": "one of: partner | ex_partner | co_parent | parent | sibling | child | close_friend | friend | colleague | trainer | therapist | doctor | contractor | other",
  "tier": 1-4 (1=partner/immediate family, 2=close, 3=important, 4=peripheral),
  "emotional_valence": "love | like | neutral | complicated | dislike",
  "emotional_notes": "1-2 sentences on the emotional texture of this relationship",
  "contact_frequency": "daily | weekly | monthly | rarely",
  "who_initiates": "leo | them | equal",
  "key_memory": "The single most specific, vivid thing from these messages — the detail that captures what this relationship actually is. 2-3 sentences, direct address to Leo.",
  "summary": "2-3 honest sentences about what this relationship is, the dynamic, what both people seem to need",
  "what_leo_wants": "inferred from messages — what does Leo seem to want from or for this relationship",
  "patterns": ["specific pattern 1", "specific pattern 2", "specific pattern 3"],
  "relationship_score": 1-10,
  "tip": "one specific, non-generic action Leo could take based on what you actually read",
  "maturity_vectors": {{
    "identity": 0-4,
    "emotional_valence": 0-4,
    "contact_pattern": 0-4,
    "shared_history": 0-4,
    "your_goal": 0-4
  }}
}}

Return ONLY raw JSON. No markdown."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if "```" in raw:
        parts = raw.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"): p = p[4:].strip()
            if p.startswith("{"): raw = p; break
    try:
        result = json.loads(raw)
        result["message_count"] = total
        result["phone"] = phone
        result["name"] = name
        return result
    except:
        return {"name": name, "phone": phone, "message_count": total, "error": "parse_failed", "raw": raw[:200]}

# ── Main ──────────────────────────────────────────────────────────────────────

print("Getting all handles from chat.db...", flush=True)
all_phones = get_all_handles()
print(f"Found {len(all_phones)} handles. Batch counting...", flush=True)

counts = batch_count_messages(all_phones)
ranked = sorted([(p, c) for p, c in counts.items() if c >= MIN_MESSAGES], key=lambda x: -x[1])
print(f"{len(ranked)} contacts with {MIN_MESSAGES}+ messages. Top {TOP_N}:")
for phone, count in ranked[:TOP_N]:
    print(f"  {phone}: {count:,}")

print(f"\nAnalyzing top {TOP_N}...", flush=True)
results = []
for i, (phone, count) in enumerate(ranked[:TOP_N]):
    print(f"\n[{i+1}/{TOP_N}] {phone} ({count:,} messages)...", flush=True)
    msgs, total = get_messages(phone)
    if not msgs:
        print("  No messages decoded, skipping")
        continue
    result = analyze_contact(phone, phone, total, msgs)
    results.append(result)
    name = result.get("relationship_type", "?")
    print(f"  → {name} | score: {result.get('relationship_score','?')} | tier: {result.get('tier','?')}")
    time.sleep(1)  # rate limit buffer

# Save
out_path = os.path.join(os.path.dirname(__file__), "full_graph_output.json")
with open(out_path, "w") as f:
    json.dump({"contacts": results, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, indent=2)

print(f"\n{'='*60}")
print(f"RELATIONSHIP GRAPH — {len(results)} contacts analyzed")
print(f"{'='*60}")
for r in results:
    if "error" not in r:
        print(f"\n{r['phone']} | {r.get('relationship_type','?')} | tier {r.get('tier','?')} | {r['message_count']:,} msgs | score {r.get('relationship_score','?')}/10")
        print(f"  {r.get('emotional_valence','?')} — {r.get('emotional_notes','')}")
        if r.get('key_memory'):
            print(f"  KEY: {r['key_memory'][:120]}...")
print(f"\nFull output saved to full_graph_output.json")
