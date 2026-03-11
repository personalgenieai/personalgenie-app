"""
fix_people_records.py
1. Merge TJ Schmidt (gmail) + +17049308241 (imessage) into one record
2. Rename +12153272252 → Barry Kerollis
3. Rename +14154307058 → Simon (trainer)
"""
import os, json, sys
sys.path.insert(0, "/Users/abhimanyugupta/PersonalGenieApp/backend")
os.chdir("/Users/abhimanyugupta/PersonalGenieApp/backend")

from supabase import create_client

SUPABASE_URL = "https://czrdhpopcqfspxahiaxe.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN6cmRocG9wY3Fmc3B4YWhpYXhlIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjkzMDgyOSwiZXhwIjoyMDg4NTA2ODI5fQ.e5CsjiHdPPyev5ns1k0HHwssdmUgDkYodwCm2A2G7OI"
USER_ID = "d7e78b66-517b-43c9-8462-555855fd34f2"

db = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_person(name_or_phone):
    r = db.table("people").select("*").eq("owner_user_id", USER_ID).eq("name", name_or_phone).execute()
    return r.data[0] if r.data else None

# ── 1. Merge TJ Schmidt + +17049308241 ─────────────────────────────────────
print("── Merging TJ Schmidt + +17049308241 ──")
tj_named = get_person("TJ Schmidt")
tj_phone = get_person("+17049308241")

if tj_named and tj_phone:
    # Combine memories (phone record is primary — more memories, higher closeness)
    mems_phone = tj_phone.get("memories") or []
    mems_named = tj_named.get("memories") or []
    merged_mems = mems_phone + mems_named

    # Pick best closeness score
    closeness = max(tj_phone.get("closeness_score") or 0, tj_named.get("closeness_score") or 0)

    # Update the phone record: give it the real name + email + merged memories
    db.table("people").update({
        "name": "TJ Schmidt",
        "phone": "+17049308241",
        "email": tj_named.get("email"),
        "memories": merged_mems,
        "closeness_score": closeness,
        "data_sources": ["imessage", "gmail"],
    }).eq("id", tj_phone["id"]).execute()

    # Re-point any moments linked to the named record → phone record
    db.table("moments").update({"person_id": tj_phone["id"]}).eq("person_id", tj_named["id"]).execute()

    # Delete the named duplicate
    db.table("people").delete().eq("id", tj_named["id"]).execute()

    print(f"  ✓ Merged into id={tj_phone['id']} | {len(merged_mems)} total memories | sources=[imessage, gmail]")
else:
    print(f"  ! TJ named={bool(tj_named)}, TJ phone={bool(tj_phone)} — skipping")

# ── 2. Rename +12153272252 → Barry Kerollis ────────────────────────────────
print("── Renaming +12153272252 → Barry Kerollis ──")
barry = get_person("+12153272252")
if barry:
    db.table("people").update({
        "name": "Barry Kerollis",
        "phone": "+12153272252",
        "data_sources": ["imessage"],
    }).eq("id", barry["id"]).execute()
    print(f"  ✓ Renamed | id={barry['id']} | {len(barry.get('memories') or [])} memories")
else:
    print("  ! +12153272252 not found")

# ── 3. Rename +14154307058 → Simon ─────────────────────────────────────────
print("── Renaming +14154307058 → Simon ──")
simon = get_person("+14154307058")
if simon:
    db.table("people").update({
        "name": "Simon",
        "phone": "+14154307058",
        "data_sources": ["imessage"],
        "relationship_type": "trainer",
    }).eq("id", simon["id"]).execute()
    print(f"  ✓ Renamed | id={simon['id']} | {len(simon.get('memories') or [])} memories")
else:
    print("  ! +14154307058 not found")

# ── Verify ──────────────────────────────────────────────────────────────────
print("\n── Final state ──")
for name in ["TJ Schmidt", "Barry Kerollis", "Simon"]:
    p = get_person(name)
    if p:
        mems = p.get("memories") or []
        sources = set(m.get("source") for m in mems)
        print(f"  {p['name']} | phone={p['phone']} | {len(mems)} memories | sources={sources} | data_sources={p.get('data_sources')}")
    else:
        print(f"  {name}: NOT FOUND")
