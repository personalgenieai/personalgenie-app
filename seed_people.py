"""
seed_people.py
1. Fix TJ Schmidt — relationship_type, gender context
2. Create Lauren Staudinger
3. Create Alice Chiu
"""
import sys
sys.path.insert(0, "/Users/abhimanyugupta/PersonalGenieApp/backend")

from supabase import create_client
import uuid

SUPABASE_URL = "https://czrdhpopcqfspxahiaxe.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN6cmRocG9wY3Fmc3B4YWhpYXhlIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjkzMDgyOSwiZXhwIjoyMDg4NTA2ODI5fQ.e5CsjiHdPPyev5ns1k0HHwssdmUgDkYodwCm2A2G7OI"
USER_ID = "d7e78b66-517b-43c9-8462-555855fd34f2"

db = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── 1. Fix TJ Schmidt ───────────────────────────────────────────────────────
print("── Fixing TJ Schmidt ──")
r = db.table("people").update({
    "relationship_type": "ex-fiancé / co-parent",
    "communication_style": "Practical and transactional with occasional warmth. Financial tensions present but both maintain politeness. Warm check-ins, supportive but distant since tense financial conversation Aug 2025.",
}).eq("owner_user_id", USER_ID).eq("name", "TJ Schmidt").execute()
print(f"  ✓ Updated {len(r.data)} record(s)")

# ── 2. Create Lauren Staudinger ────────────────────────────────────────────
print("── Creating Lauren Staudinger ──")
lauren = {
    "id": str(uuid.uuid4()),
    "owner_user_id": USER_ID,
    "name": "Lauren Staudinger",
    "phone": None,
    "email": None,
    "relationship_type": "close friend / NYU Stern classmate",
    "closeness_score": 0.82,
    "communication_style": "Warm and loyal. Lauren is the one who keeps showing up. Westchester life with husband David and daughter Mirabelle. You're 'tio Leo' to Mirabelle.",
    "data_sources": ["contacts"],
    "memories": [
        {
            "source": "relationship_analysis",
            "description": "NYU Stern classmate — one of the people who stayed close after graduation"
        },
        {
            "source": "relationship_analysis",
            "description": "Lives in Westchester, NY with husband David and daughter Mirabelle — Mirabelle calls Leo 'tio Leo'"
        },
        {
            "source": "relationship_analysis",
            "description": "Mirabelle had a recital that Lauren carried largely alone — Leo wasn't there for it"
        },
        {
            "source": "relationship_analysis",
            "description": "David had a health scare (Oct/Nov 2025) that was never fully addressed or followed up on by Leo"
        },
        {
            "source": "relationship_analysis",
            "description": "Lauren has a dream connected to Portugal — she's mentioned it but it's never been properly explored"
        },
        {
            "source": "relationship_analysis",
            "description": "Friendship has some drift — Lauren tends to initiate more; Leo owes her meaningful follow-through"
        },
    ],
    "suggested_moments": [
        {
            "title": "The Recital She Carried Alone",
            "timing": "RIGHT NOW",
            "description": "Text asking for the full recital video, then send a real voice memo reaction. 'Tio Leo clapped so loud the neighbors complained.'"
        },
        {
            "title": "The Birthday That Still Happened",
            "timing": "THIS WEEK",
            "description": "Ship Portuguese wine to Westchester. Note tied to Portugal dream, not an apology. 'Call me when you open it.'"
        },
        {
            "title": "The David Thing Nobody Asks About",
            "timing": "THIS WEEK",
            "description": "On a call, ask how she's actually doing *about* David's health scare (Oct/Nov 2025). Nobody else asks — be the one who does."
        },
    ],
}
r = db.table("people").insert(lauren).execute()
print(f"  ✓ Created Lauren Staudinger | id={r.data[0]['id']}")

# ── 3. Create Alice Chiu ───────────────────────────────────────────────────
print("── Creating Alice Chiu ──")
alice = {
    "id": str(uuid.uuid4()),
    "owner_user_id": USER_ID,
    "name": "Alice Chiu",
    "phone": None,
    "email": None,
    "relationship_type": "close friend",
    "closeness_score": 0.90,
    "communication_style": "Alice initiates far more than Leo does. Deep friendship, 9/10 closeness. Shared interest in cannabis (her 'tree'). Warm, loyal, carries more of the friendship weight.",
    "data_sources": ["contacts", "imessage"],
    "memories": [
        {
            "source": "relationship_analysis",
            "description": "Close friend, closeness score 9/10 — one of Leo's most important relationships"
        },
        {
            "source": "relationship_analysis",
            "description": "Alice initiates contact far more often than Leo does — imbalance Leo is aware of"
        },
        {
            "source": "relationship_analysis",
            "description": "Shared interest in cannabis — it's a recurring thread in their friendship ('the tree')"
        },
        {
            "source": "relationship_analysis",
            "description": "Warm, loyal, emotionally present — the kind of friend who shows up without being asked"
        },
    ],
    "suggested_moments": [
        {
            "title": "Just Reach First",
            "timing": "THIS WEEK",
            "description": "Text Alice first — no reason needed. She's been carrying the initiating. Let her know you think about her."
        },
    ],
}
r = db.table("people").insert(alice).execute()
print(f"  ✓ Created Alice Chiu | id={r.data[0]['id']}")

print("\nDone.")
