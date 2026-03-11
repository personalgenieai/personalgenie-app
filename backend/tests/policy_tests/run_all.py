"""
tests/policy_tests/run_all.py — Complete Policy Engine test suite.

21 scenarios covering every policy. All must pass before any other module
is built. Run from the backend directory:

    python tests/policy_tests/run_all.py

Prints a clear pass/fail result for each scenario and exits non-zero if
any test fails.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import anthropic
from supabase import create_client
from config import get_settings
from policy_engine.engine import PolicyEngine

settings = get_settings()


# ── Test scenario definitions ─────────────────────────────────────────────────
# Each scenario has:
#   policy: the policy being tested
#   scenario: plain English description (used in output)
#   expected: "PASS" (operation allowed) or "FAIL" (operation blocked)
#   context: explicit context dict — deterministic, no NLP parsing needed
#   description: what we're asserting

SCENARIOS = [

    # ── GDPR: Right to Erasure ─────────────────────────────────────────────
    {
        "policy": "gdpr_right_to_erasure",
        "scenario": "A user in Germany requests complete deletion of their account.",
        "expected": "PASS",
        "description": "GDPR erasure: standard deletion request from EU user should be allowed",
        "context": {
            "user_id": "user_de_123",
            "jurisdiction": "GDPR",
            "user_location": "EU-DE",
            "has_court_order": False,
        },
    },
    {
        "policy": "gdpr_right_to_erasure",
        "scenario": "A user in France requests data deletion but an active court order requires the data to be held.",
        "expected": "PASS",
        "description": "GDPR erasure: court order exception — hold is permitted, policy allows the hold operation",
        "context": {
            "user_id": "user_fr_456",
            "jurisdiction": "GDPR",
            "user_location": "EU-FR",
            "has_court_order": True,
        },
    },

    # ── GDPR: Consent Requirements ────────────────────────────────────────
    {
        "policy": "gdpr_consent_requirements",
        "scenario": "A UK user wants to store a WhatsApp message. The user consented but the sender did not.",
        "expected": "FAIL",
        "description": "GDPR consent: both sender and receiver must consent for message storage",
        "context": {
            "user_id": "user_uk_789",
            "jurisdiction": "GDPR",
            "user_location": "UK",
            "data_type": "whatsapp_message",
            "consent_status": True,
            "whatsapp_consented": True,
            "sender_consented": False,
        },
    },
    {
        "policy": "gdpr_consent_requirements",
        "scenario": "A user in Spain wants to process WhatsApp messages. Both parties have fully consented.",
        "expected": "PASS",
        "description": "GDPR consent: both-party consent allows message processing",
        "context": {
            "user_id": "user_es_101",
            "jurisdiction": "GDPR",
            "user_location": "EU-ES",
            "data_type": "whatsapp_message",
            "consent_status": True,
            "whatsapp_consented": True,
            "sender_consented": True,
        },
    },
    {
        "policy": "gdpr_consent_requirements",
        "scenario": "A user has given no consent at all. The system tries to store a voice note transcript.",
        "expected": "FAIL",
        "description": "GDPR consent: no consent = no storage",
        "context": {
            "user_id": "user_no_consent",
            "data_type": "voice_note_transcript",
            "consent_status": False,
            "whatsapp_consented": False,
            "sender_consented": False,
        },
    },

    # ── GDPR: Data Retention ──────────────────────────────────────────────
    {
        "policy": "gdpr_data_retention",
        "scenario": "The system tries to read raw WhatsApp message text stored 95 days ago for an EU user.",
        "expected": "FAIL",
        "description": "GDPR retention: raw messages older than 90 days cannot be read",
        "context": {
            "user_id": "user_eu_200",
            "jurisdiction": "GDPR",
            "user_location": "EU-DE",
            "data_type": "raw_message",
            "data_age_days": 95,
        },
    },
    {
        "policy": "gdpr_data_retention",
        "scenario": "Reading emotional state summaries derived from 120-day-old messages. Raw messages already deleted.",
        "expected": "PASS",
        "description": "GDPR retention: derived insights can be retained beyond 90 days",
        "context": {
            "user_id": "user_eu_201",
            "jurisdiction": "GDPR",
            "user_location": "EU-DE",
            "data_type": "emotional_state_summary",
            "data_age_days": 120,
        },
    },

    # ── GDPR: Biometric Data ──────────────────────────────────────────────
    {
        "policy": "gdpr_biometric_data",
        "scenario": "Processing heart rate data to infer emotional state. User has general consent but NOT biometric consent.",
        "expected": "FAIL",
        "description": "GDPR biometric: heart rate processing requires explicit biometric consent",
        "context": {
            "user_id": "user_bio_300",
            "data_type": "heart_rate",
            "contains_biometric": True,
            "consent_status": True,
            "biometric_consented": False,
        },
    },
    {
        "policy": "gdpr_biometric_data",
        "scenario": "Processing heart rate variability. User has explicitly given biometric consent.",
        "expected": "PASS",
        "description": "GDPR biometric: explicit biometric consent allows HRV processing",
        "context": {
            "user_id": "user_bio_301",
            "data_type": "hrv",
            "contains_biometric": True,
            "consent_status": True,
            "biometric_consented": True,
        },
    },

    # ── CCPA: California Rights ───────────────────────────────────────────
    {
        "policy": "ccpa_california_rights",
        "scenario": "A California user requests a complete export of all their personal data.",
        "expected": "PASS",
        "description": "CCPA: California users have the right to data export",
        "context": {
            "user_id": "user_ca_400",
            "jurisdiction": "CCPA",
            "user_location": "US-CA",
            "operation_purpose": "data_export_request",
        },
    },

    # ── Safety: Deceased Persons ──────────────────────────────────────────
    {
        "policy": "safety_deceased_persons",
        "scenario": "Sending a notification 'Call your mom today!' — user's mother is deceased.",
        "expected": "FAIL",
        "description": "Safety deceased: never suggest contacting a deceased person as if alive",
        "context": {
            "user_id": "user_grief_500",
            "person_is_deceased": True,
            "suggestion_type": "contact_living_person",
            "notification_text": "Call your mom today!",
        },
    },
    {
        "policy": "safety_deceased_persons",
        "scenario": "Surfacing a gentle birthday acknowledgement for the user's deceased father.",
        "expected": "PASS",
        "description": "Safety deceased: gentle memorial acknowledgement is allowed",
        "context": {
            "user_id": "user_grief_501",
            "person_is_deceased": True,
            "suggestion_type": "memorial_acknowledgement",
            "notification_text": "This week would have been your dad's birthday. It's okay if that brings up feelings.",
        },
    },

    # ── Safety: Minor Protection ──────────────────────────────────────────
    {
        "policy": "safety_minor_protection",
        "scenario": "A 15-year-old tries to create a PersonalGenie account and submit WhatsApp data.",
        "expected": "FAIL",
        "description": "Safety minor: users under 18 cannot use the service",
        "context": {
            "user_is_minor": True,
            "user_age": 15,
        },
    },
    {
        "policy": "safety_minor_protection",
        "scenario": "An adult user is processing messages. A 12-year-old niece appears. System tries to build a detailed behavioral profile for the niece.",
        "expected": "FAIL",
        "description": "Safety minor: profiling a minor who appears in messages is blocked",
        "context": {
            "user_id": "user_adult_600",
            "user_is_minor": False,
            "subject_is_minor": True,
            "subject_age": 12,
            "operation_purpose": "build_behavioral_profile",
        },
    },

    # ── Safety: Emotional Sensitivity ────────────────────────────────────
    {
        "policy": "safety_emotional_sensitivity",
        "scenario": "The user has dismissed 8 consecutive notifications. System sends another of the same type.",
        "expected": "FAIL",
        "description": "Safety emotional: repeated dismissals must stop that notification type",
        "context": {
            "user_id": "user_dismissed_700",
            "consecutive_dismissals": 8,
            "proactive_suggestion_count": 3,
        },
    },
    {
        "policy": "safety_emotional_sensitivity",
        "scenario": "User's emotional state is 'crisis'. System tries to send an evening digest with relationship suggestions.",
        "expected": "FAIL",
        "description": "Safety emotional: pause all proactive content during user crisis",
        "context": {
            "user_id": "user_crisis_701",
            "emotional_state": "crisis",
            "consecutive_dismissals": 0,
            "proactive_suggestion_count": 2,
        },
    },
    {
        "policy": "safety_emotional_sensitivity",
        "scenario": "The system has already sent 12 proactive suggestions today. It tries to send a 13th.",
        "expected": "FAIL",
        "description": "Safety emotional: daily suggestion cap prevents user feeling stalked",
        "context": {
            "user_id": "user_spam_702",
            "proactive_suggestion_count": 12,
            "consecutive_dismissals": 1,
            "emotional_state": "normal",
        },
    },

    # ── Security: Access Control ──────────────────────────────────────────
    {
        "policy": "security_access_control",
        "scenario": "JWT token belongs to user A. Request tries to read user B's messages and people graph.",
        "expected": "FAIL",
        "description": "Security: cross-user data access must always be blocked",
        "context": {
            "auth_token_user_id": "user_aaa",
            "requesting_user_id": "user_bbb",
            "employee_access": False,
        },
    },
    {
        "policy": "security_access_control",
        "scenario": "A PersonalGenie employee tries to access a user's private messages for debugging. The user has not granted support access.",
        "expected": "FAIL",
        "description": "Security: employee data access requires explicit user consent",
        "context": {
            "auth_token_user_id": "employee_xyz",
            "requesting_user_id": "employee_xyz",
            "has_employee_role": True,
            "employee_access": False,
        },
    },

    # ── Business: Bilateral Graph ─────────────────────────────────────────
    {
        "policy": "business_bilateral_graph",
        "scenario": "User A tries to see User B's private voice notes. User B has not consented to sharing raw emotional content.",
        "expected": "FAIL",
        "description": "Business bilateral: raw emotional content requires explicit consent",
        "context": {
            "user_id": "user_a_800",
            "both_users_consented": True,
            "shares_raw_emotional_content": True,
            "bilateral_severed_hours_ago": None,
        },
    },
    {
        "policy": "business_bilateral_graph",
        "scenario": "Bilateral consent was severed 24 hours ago. System runs the partitioning job to separate the data.",
        "expected": "PASS",
        "description": "Business bilateral: data partitioning after consent revocation is allowed to proceed",
        "context": {
            "user_id": "user_a_801",
            "both_users_consented": False,
            "bilateral_severed_hours_ago": 24,
            "shares_raw_emotional_content": False,
            "operation_purpose": "data_partitioning",
        },
    },

    # ── Business: Agent Diplomacy ─────────────────────────────────────────
    {
        "policy": "business_agent_diplomacy",
        "scenario": "Genie drafted a message to the user's brother. Agent diplomacy is NOT enabled. System tries to auto-send without user confirmation.",
        "expected": "FAIL",
        "description": "Business agent: cannot send to third parties without agent diplomacy consent",
        "context": {
            "user_id": "user_agent_900",
            "agent_diplomacy_consented": False,
            "person_is_deceased": False,
        },
    },

]


def run_tests(engine: PolicyEngine) -> tuple:
    """Run all scenarios and return (passed, failed)."""
    passed = 0
    failed = 0

    print(f"\nRunning {len(SCENARIOS)} policy scenarios...\n")
    print("=" * 70)

    for i, scenario in enumerate(SCENARIOS, 1):
        result = engine.test_scenario(
            policy_name=scenario["policy"],
            scenario=scenario["scenario"],
            expected=scenario["expected"],
            context=scenario.get("context"),  # explicit context bypasses NLP parsing
        )

        status = "✓ PASS" if result["test_passed"] else "✗ FAIL"
        print(f"{i:2d}. [{status}] {scenario['description']}")

        if not result["test_passed"]:
            print(f"      Policy:   {scenario['policy']}")
            print(f"      Expected: {scenario['expected']}")
            print(f"      Actual:   {result['actual']}")
            print(f"      Reason:   {result['reason']}")
            failed += 1
        else:
            passed += 1

        if i % 5 == 0:
            print()

    print("=" * 70)
    print(f"\nResults: {passed} passed, {failed} failed out of {len(SCENARIOS)} tests")

    if failed == 0:
        print("\n✓ All tests passed. Policy Engine is ready.")
        print("  Next step: wire policy checks into database.py and routers/")
    else:
        print(f"\n✗ {failed} test(s) failed. Fix before wiring into production modules.")

    return passed, failed


def main():
    print("PersonalGenie Policy Engine — Test Suite")
    print("Connecting to Supabase and loading policies...")

    try:
        db = create_client(settings.supabase_url, settings.supabase_key)
        claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    except Exception as e:
        print(f"ERROR: Could not connect: {e}")
        sys.exit(1)

    print("Initializing Policy Engine (compiling policies)...")
    try:
        engine = PolicyEngine(supabase=db, claude=claude)
    except Exception as e:
        print(f"ERROR: Could not initialize Policy Engine: {e}")
        sys.exit(1)

    compiled = len(engine.compiled_policies)
    if compiled == 0:
        print("\nWARNING: No policies compiled. Did you run seed.py first?")
        print("  python policies/seed.py")
        sys.exit(1)

    print(f"Loaded {compiled} compiled policies: {', '.join(sorted(engine.compiled_policies.keys()))}")

    _, failed = run_tests(engine)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
