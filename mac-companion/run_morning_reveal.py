"""
Generates the actual first morning reveal for Abhimanyu
using real iMessage data from TJ, Simon, and Barry.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import anthropic
from chat_reader import get_messages

client = anthropic.Anthropic()

CONTACTS = [
    {"name": "TJ",     "phone": "+17049308241", "role": "ex-fiancée, co-parent of Vindaloo"},
    {"name": "Simon",  "phone": "+14154307058", "role": "personal trainer"},
    {"name": "Barry",  "phone": "+12153272252", "role": "close friend, dancer/choreographer in Seattle"},
]

def sample(messages, n_oldest=150, n_mid=300, n_recent=1000):
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

def build_transcript(name, messages):
    lines = []
    for m in messages:
        speaker = "Leo" if m["is_from_me"] else name
        lines.append(f"{speaker}: {m['text']}")
    return "\n".join(lines)

# --- Load all conversations ---
print("Loading messages...", flush=True)
convos = {}
for c in CONTACTS:
    msgs, total = get_messages(c["phone"])
    sampled = sample(msgs)
    convos[c["name"]] = {
        "total": total,
        "sampled": len(sampled),
        "transcript": build_transcript(c["name"], sampled),
        "role": c["role"],
    }
    print(f"  {c['name']}: {total:,} total → {len(sampled):,} sampled", flush=True)

# --- Known context from memory ---
user_context = """
User: Abhimanyu ("Leo")
- Has a dog named Vindaloo, co-parented with TJ
- Recently completed a Vipassana retreat (Feb 18–Mar 1, 2026)
- Brother: Arpan
- Based in San Francisco
- Goes to gym regularly, works with Simon as personal trainer
- Has done SoulCycle with TJ
- Sees a therapist weekly for mental health
- Goals around TJ: evolve from ex-fiancée to genuine best friends
"""

prompt = f"""You are Personal Genie. You have spent the night reading through Leo's iMessage conversations with his three most important people. Now it's morning and you are delivering his first morning reveal.

Your voice: warm, perceptive, direct. Like a brilliant chief of staff who read everything and is now telling you what they noticed. Not a list of facts — a conversation that feels like someone finally sees you clearly.

What you know about Leo:
{user_context}

---

CONVERSATION WITH TJ ({convos['TJ']['total']:,} total messages, role: {convos['TJ']['role']}):
{convos['TJ']['transcript'][:60000]}

---

CONVERSATION WITH SIMON ({convos['Simon']['total']:,} total messages, role: {convos['Simon']['role']}):
{convos['Simon']['transcript'][:25000]}

---

CONVERSATION WITH BARRY ({convos['Barry']['total']:,} total messages, role: {convos['Barry']['role']}):
{convos['Barry']['transcript'][:25000]}

---

Write Leo's first morning reveal. This is what he sees when he opens the app on Day 1.

Rules:
- Speak directly to Leo as "you" — never refer to him in third person
- Reference specific, real things from the messages — not general observations
- Connect across domains: relationships + health + how he's doing as a person
- Surface the one thing about each person that would make Leo think "how did it know that"
- End with what you still need to understand — framing gaps as curiosity, not incompleteness
- Total length: 400–600 words
- Tone: the best friend who also read everything and is being honest

Do NOT write this as bullet points or cards. Write it as the Genie speaking — one flowing morning message.
"""

print("\nSending to Claude...", flush=True)
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=2000,
    messages=[{"role": "user", "content": prompt}],
)

reveal = response.content[0].text.strip()

print("\n" + "="*60)
print("MORNING REVEAL — DRAFT 1")
print("="*60)
print(reveal)
print("="*60)

with open("morning_reveal_output.txt", "w") as f:
    f.write(reveal)
print("\nSaved to morning_reveal_output.txt")
