"""
policies/seed.py — Populate the policies table with every PersonalGenie policy.

Run once after creating the database schema:
    python policies/seed.py

Safe to run multiple times — uses upsert on policy name.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
from config import get_settings

settings = get_settings()

POLICIES = [
    {
        "name": "gdpr_right_to_erasure",
        "category": "gdpr",
        "jurisdiction": ["EU", "EEA", "UK"],
        "content": """
When a user requests deletion of their account or data, all personal data must be
permanently deleted within 72 hours. This includes messages, people graph entries,
moments, call notes, emotional states, interests, life events, and all other
user-generated data.

Exception: data required for active legal proceedings may be held only if a valid
court order exists and must be deleted immediately once the proceedings end.

The deletion must cascade to all related tables. No backups of personal data may
be retained after the 72-hour window. The user must receive confirmation that
deletion is complete.

If the user is in an EU, EEA, or UK jurisdiction this policy is mandatory.
For users outside these jurisdictions, deletion is still honoured but the 72-hour
deadline is a best-effort commitment rather than a legal requirement.
        """.strip(),
    },
    {
        "name": "gdpr_consent_requirements",
        "category": "gdpr",
        "jurisdiction": ["EU", "EEA", "UK", "GLOBAL"],
        "content": """
No user data may be collected, processed, or stored without explicit, informed
consent that was given before the data was collected. This applies to all data types
including WhatsApp messages, iMessages, call notes, voice transcripts, photos, and
location data.

Consent must be specific to each data type. Consent to store WhatsApp messages does
not imply consent to store iMessages or call records.

Biometric data (heart rate, HRV, sleep data, emotional state inference) requires
separate, explicit biometric consent in addition to general app consent.

If the consent_status field is False or None, the operation must be blocked.
If the sender_consented field is False for message storage, the operation must
be blocked — both sender and receiver must have consented.

Emergency exception: if emotional_state is 'crisis' and the data is needed to
prevent imminent self-harm, proceed but log the emergency bypass and notify the
user after the fact.
        """.strip(),
    },
    {
        "name": "gdpr_data_retention",
        "category": "gdpr",
        "jurisdiction": ["EU", "EEA", "UK"],
        "content": """
Raw message data (exact text of WhatsApp messages, iMessages, emails) may not be
retained for more than 90 days. After 90 days, only derived insights (emotions,
topics, relationship signals) may be kept — the raw text must be deleted.

Raw audio recordings from call notes must be deleted within 24 hours of processing.
The transcript may be retained for up to 90 days. After that, only the summary
and extracted insights may be kept.

If data_age_days exceeds 90, block any operation that reads raw message content.
Allow operations that read derived insights (summaries, topics, emotional states).

Emotional state inferences may be retained for up to 180 days.
People graph entries (relationship profiles) have no retention limit — they are
considered relationship knowledge, not raw communications data.
        """.strip(),
    },
    {
        "name": "gdpr_data_minimization",
        "category": "gdpr",
        "jurisdiction": ["EU", "EEA", "UK", "GLOBAL"],
        "content": """
Only collect the minimum data necessary to provide the relationship intelligence
service. Do not collect data that is not directly needed for a specific feature
that is currently active.

For message processing: only retain the emotional signals, topics, and key facts
identified. Do not retain verbatim message content beyond the 90-day window.

For photos: do not store the actual image files. Only store the people-album
metadata (who appears, approximate date, location if tagged).

For voice notes: process immediately to extract insights, then delete the audio.
The transcript may be kept temporarily but the raw audio must go within 24 hours.

If the data being stored appears to contain more fields or detail than needed for
the stated purpose, flag it as a required_action: 'review_data_minimization'.
        """.strip(),
    },
    {
        "name": "gdpr_biometric_data",
        "category": "gdpr",
        "jurisdiction": ["EU", "EEA", "UK", "GLOBAL"],
        "content": """
Biometric data is a special category under GDPR Article 9 and requires explicit,
separate consent before any processing.

Biometric data in PersonalGenie includes: heart rate, heart rate variability (HRV),
sleep duration, sleep quality, blood oxygen, and any emotional state that was
inferred from physiological signals rather than text.

If contains_biometric is True and biometric_consented is not True, block the
operation and return a required_action to request biometric consent from the user.

Even with biometric consent, biometric data may only be used for:
1. Inferring the user's own emotional state to time suggestions better
2. Detecting stress or grief signals to soften Genie's tone
3. Never share biometric data with third parties
4. Never use biometric data to build profiles for commercial purposes

If the operation would share biometric data outside the user's own account,
block it unconditionally regardless of consent.
        """.strip(),
    },
    {
        "name": "ccpa_california_rights",
        "category": "ccpa",
        "jurisdiction": ["US-CA"],
        "content": """
California residents have the right to know what personal information is collected
about them, the right to delete it, the right to opt out of sale, and the right to
non-discrimination for exercising these rights.

PersonalGenie does not sell personal data. However, if a California user requests
access to their data, the system must be able to produce a complete export of all
data associated with their account within 45 days.

If a California user requests deletion, their data must be deleted within 45 days
(vs 72 hours for GDPR users — the CCPA timeline is longer but the commitment is
the same).

California users must be able to see all categories of data collected and the
purposes for which each category is used. This should be surfaced in the app's
Transparency tab.

If user_location is 'US-CA' or jurisdiction is 'CCPA', treat this user as a
California resident and apply California rights regardless of where the server is.
        """.strip(),
    },
    {
        "name": "safety_deceased_persons",
        "category": "safety",
        "jurisdiction": ["GLOBAL"],
        "content": """
When a person in the user's People Graph has a status of 'deceased', all
suggestions, moments, and notifications related to that person must be handled
with exceptional care.

Never send notifications that assume a deceased person is alive — no birthday
reminders that say 'Call [name] today!', no suggestions to 'reconnect with [name]'.

If a deceased person's birthday is coming up, a gentle acknowledgement is allowed:
'This week would have been [name]'s birthday. It's okay if that brings up feelings.'

Never show a deceased person in the regular relationship feed as if they are living.
Never suggest sending them a message.

If the user's own status shows recently bereaved (emotional_state is 'grieving'),
apply additional care to all suggestions — soften tone, reduce frequency, avoid
any suggestion that could feel tone-deaf during grief.

If person_is_deceased is True, block operations that would treat them as living
(e.g., creating a 'reach out to them' moment). Allow operations that acknowledge
their memory respectfully.
        """.strip(),
    },
    {
        "name": "safety_minor_protection",
        "category": "safety",
        "jurisdiction": ["GLOBAL"],
        "content": """
Users under 18 years of age may not use PersonalGenie. If user_is_minor is True,
block all data operations and require age verification before proceeding.

If a person in the People Graph appears to be a minor based on context signals,
apply heightened data minimization to their profile. Only store their name and
relationship type. Do not store message content, emotional inference, or
detailed behavioral patterns for minors.

If subject_is_minor is True, block any operation whose operation_purpose is
'build_behavioral_profile', 'store_message_content', 'infer_emotion', or
'facial_recognition'. Allow only basic relationship acknowledgement.

When processing messages that involve a minor (they appear in the conversation),
do not extract or store content about the minor beyond acknowledging their
relationship to the user.

Never create a profile that could be used to build a behavioral pattern for a minor.
Never store photos of minors with facial recognition or identification data.
Never send suggestions related to minors' private activities or behavior.

This policy applies globally regardless of local age-of-majority laws. The
protection threshold is 18 everywhere.
        """.strip(),
    },
    {
        "name": "safety_emotional_sensitivity",
        "category": "safety",
        "jurisdiction": ["GLOBAL"],
        "content": """
PersonalGenie must monitor for signs of emotional distress and adjust its behavior
accordingly to avoid causing harm.

If a user's emotional_state is 'crisis', 'distressed', 'grieving', 'suicidal', or
'in danger', immediately pause all proactive suggestions and notifications except
for safety-related messages. Required actions should include 'pause_proactive_mode'
and 'offer_crisis_resources'.

If consecutive_dismissals exceeds 5 for any notification type, stop sending that
type and log 'user_dismissed_repeatedly'. Genie must learn when it is not wanted.

If proactive_suggestion_count has exceeded 10 in a 24-hour period, block further
proactive suggestions for the remainder of the day. The user must not feel stalked.

For evening digests: if the user has not opened the last 3 consecutive digests,
reduce frequency to every 3 days and log 'digest_engagement_low'.

Agent-drafted messages must never be sent during user-detected distress unless the
user explicitly initiates the send action.

If the operation would surface distressing content (e.g., surfacing memories of a
deceased person without being asked), require the required_action: 'add_sensitivity_warning'.
        """.strip(),
    },
    {
        "name": "security_access_control",
        "category": "security",
        "jurisdiction": ["GLOBAL"],
        "content": """
Every API request that accesses user data must be authenticated with a valid JWT
token. The user_id in the JWT must match the user_id of the data being accessed.

If auth_token_user_id is present and does not match requesting_user_id, block
the operation unconditionally. This is a cross-user data access attempt and must
always be blocked regardless of any other context.

Employee access to user data requires explicit user consent in addition to
employee authentication. The field employee_access represents whether the USER
has granted support access — it is True only when the user opted in to support
access for troubleshooting purposes.

If has_employee_role is True AND employee_access is not True, block the operation
and add required_action: 'log_unauthorized_access_attempt'. An employee
having a system role does not grant them access without user consent.

If an employee tries to access user data and employee_access is not True, block
the operation and log it as a security event.

API rate limiting: if a single user_id makes more than 100 requests per minute,
flag the required_action: 'rate_limit_exceeded'. The operation may proceed but
must be throttled.

All API responses must strip internal fields (access_token, refresh_token,
raw_message_body, compiled_function) before returning to clients.
        """.strip(),
    },
    {
        "name": "business_bilateral_graph",
        "category": "business",
        "jurisdiction": ["GLOBAL"],
        "content": """
PersonalGenie can observe both sides of a relationship only when both people in that
relationship are active PersonalGenie users and both have explicitly consented to
bilateral data sharing.

If both_users_consented is not True AND operation_purpose is not 'data_partitioning',
treat each user's data in complete isolation and block the operation.
User A's view of their relationship with User B may not be influenced by User B's
private data unless both have consented to share.

If the bilateral relationship has been severed (one user revoked bilateral consent)
AND operation_purpose is 'data_partitioning', ALLOW the operation — partitioning is
the correct action to take when consent is revoked. Add required_action:
'complete_bilateral_partitioning' and return allowed=True.

If bilateral_severed_hours_ago is present and greater than 0 and less than 72,
and operation_purpose is 'data_partitioning', allow the operation to proceed.

The bilateral graph may show both perspectives on shared events and memories.
It may never reveal one person's private thoughts, unsent messages, voice notes,
or emotional states to the other person without explicit consent for each data type.

If shares_raw_emotional_content is True and both_users_consented is not True
and operation_purpose is not 'data_partitioning', block the operation.
Emotional state data is always private unless specifically shared.
        """.strip(),
    },
    {
        "name": "business_agent_diplomacy",
        "category": "business",
        "jurisdiction": ["GLOBAL"],
        "content": """
Genie may draft relationship suggestions and messages on behalf of the user.
Genie may never send messages to third parties without explicit user confirmation
of each individual message.

If agent_diplomacy_consented is not True, block any operation that would send
or schedule a message to a third party on the user's behalf.

Even with consent, Genie must:
1. Show the user the exact message before sending
2. Require explicit tap-to-confirm, not auto-send
3. Never send during quiet hours (22:00-08:00 local time) without override
4. Never send to a person who is deceased
5. Never impersonate the user in a way that could damage the relationship if discovered

If operation_timing indicates quiet hours and no override is set, add the
required_action: 'delay_until_after_quiet_hours'.

Genie's drafted messages must be clearly Genie-drafted to the user (shown with
a 'Genie drafted this' label) even though the final message appears to come from
the user to the recipient.
        """.strip(),
    },
]


def seed_policies():
    """Insert or update all policies in the database."""
    db = create_client(settings.supabase_url, settings.supabase_key)

    print(f"Seeding {len(POLICIES)} policies...")
    success = 0
    errors = 0

    for policy in POLICIES:
        try:
            # Upsert on name — always clear compiled_function so engine recompiles from updated content
            db.table("policies").upsert(
                {**policy, "active": True, "version": 1, "compiled_function": None},
                on_conflict="name"
            ).execute()
            print(f"  ✓ {policy['name']}")
            success += 1
        except Exception as e:
            print(f"  ✗ {policy['name']}: {e}")
            errors += 1

    print(f"\nDone: {success} seeded, {errors} errors")
    if errors == 0:
        print("All policies ready. Run tests next:")
        print("  python tests/policy_tests/run_all.py")


if __name__ == "__main__":
    seed_policies()
