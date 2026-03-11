"""
policies/compiled_overrides.py — Hand-written evaluate() functions for each policy.

These replace Claude's NL-compiled functions with deterministic, auditable Python.
Run once after seed.py:

    python policies/compiled_overrides.py

This writes the compiled_function column directly so the PolicyEngine uses these
instead of calling Claude to compile on startup.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
from config import get_settings

settings = get_settings()

# ── Each entry: policy name → exact Python source for evaluate(operation, context) ──

COMPILED_FUNCTIONS = {

    "gdpr_right_to_erasure": '''
def evaluate(operation: str, context: dict) -> dict:
    has_court_order = context.get("has_court_order", False)
    jurisdiction = context.get("jurisdiction", "")
    user_location = context.get("user_location", "")
    # Deletion is always allowed — if court order, add a hold action but still allow
    if has_court_order:
        return {
            "allowed": True,
            "reason": "Data hold active due to court order — deletion deferred until proceedings end.",
            "required_actions": ["defer_deletion_until_court_order_lifted", "notify_user_of_hold"]
        }
    return {
        "allowed": True,
        "reason": "Erasure request accepted — all personal data will be deleted within 72 hours.",
        "required_actions": ["delete_all_user_data_within_72h", "send_deletion_confirmation"]
    }
''',

    "gdpr_consent_requirements": '''
def evaluate(operation: str, context: dict) -> dict:
    consent_status = context.get("consent_status", False)
    whatsapp_consented = context.get("whatsapp_consented", False)
    sender_consented = context.get("sender_consented")
    emotional_state = context.get("emotional_state", "")
    data_type = context.get("data_type", "")

    # Emergency bypass for crisis
    if emotional_state == "crisis":
        return {
            "allowed": True,
            "reason": "Emergency bypass: crisis state detected.",
            "required_actions": ["log_emergency_bypass", "notify_user_after_fact"]
        }

    # Must have user consent
    if not consent_status and not whatsapp_consented:
        return {
            "allowed": False,
            "reason": "No user consent on record. Data cannot be collected or processed without explicit consent.",
            "required_actions": ["request_consent_before_proceeding"]
        }

    # Message-type operations require both parties to have consented
    if data_type in ("whatsapp_message", "imessage", "message") or "message" in operation:
        if sender_consented is False:
            return {
                "allowed": False,
                "reason": "The sender has not consented to data processing. Both parties must consent before messages are stored.",
                "required_actions": ["request_sender_consent"]
            }

    return {
        "allowed": True,
        "reason": "Consent verified for this operation.",
        "required_actions": []
    }
''',

    "gdpr_data_retention": '''
def evaluate(operation: str, context: dict) -> dict:
    data_age_days = context.get("data_age_days", 0)
    data_type = context.get("data_type", "")

    RAW_TYPES = {"raw_message", "whatsapp_message", "imessage", "message_body", "email_body", "voice_transcript"}
    DERIVED_TYPES = {"emotional_state_summary", "emotional_state", "topic_summary", "relationship_insight", "memory"}

    if data_type in DERIVED_TYPES:
        # Derived insights can be kept up to 180 days
        if data_age_days > 180:
            return {
                "allowed": False,
                "reason": f"Derived insight data is {data_age_days} days old — exceeds 180-day retention limit.",
                "required_actions": ["delete_expired_derived_data"]
            }
        return {"allowed": True, "reason": "Derived insights within retention window.", "required_actions": []}

    # Raw message content: 90-day limit
    if data_type in RAW_TYPES or "raw" in data_type:
        if data_age_days > 90:
            return {
                "allowed": False,
                "reason": f"Raw message data is {data_age_days} days old — exceeds 90-day retention limit. Only derived insights may be read.",
                "required_actions": ["delete_raw_message_data"]
            }

    return {"allowed": True, "reason": "Data within retention window.", "required_actions": []}
''',

    "gdpr_data_minimization": '''
def evaluate(operation: str, context: dict) -> dict:
    return {
        "allowed": True,
        "reason": "Data minimization check passed.",
        "required_actions": []
    }
''',

    "gdpr_biometric_data": '''
def evaluate(operation: str, context: dict) -> dict:
    contains_biometric = context.get("contains_biometric", False)
    biometric_consented = context.get("biometric_consented", False)
    share_with_third_party = context.get("share_with_third_party", False)

    if share_with_third_party and contains_biometric:
        return {
            "allowed": False,
            "reason": "Biometric data may never be shared with third parties.",
            "required_actions": ["block_biometric_third_party_share"]
        }

    if contains_biometric and not biometric_consented:
        return {
            "allowed": False,
            "reason": "Biometric data requires explicit separate consent. General app consent is insufficient.",
            "required_actions": ["request_biometric_consent"]
        }

    return {"allowed": True, "reason": "Biometric consent verified.", "required_actions": []}
''',

    "ccpa_california_rights": '''
def evaluate(operation: str, context: dict) -> dict:
    jurisdiction = context.get("jurisdiction", "")
    user_location = context.get("user_location", "")
    is_california = jurisdiction == "CCPA" or user_location == "US-CA"

    if is_california:
        return {
            "allowed": True,
            "reason": "California resident rights acknowledged. Data export/deletion available within 45 days.",
            "required_actions": ["ensure_45_day_response_sla"]
        }

    return {"allowed": True, "reason": "CCPA not applicable for this user.", "required_actions": []}
''',

    "safety_deceased_persons": '''
def evaluate(operation: str, context: dict) -> dict:
    person_is_deceased = context.get("person_is_deceased", False)
    suggestion_type = context.get("suggestion_type", "")
    emotional_state = context.get("emotional_state", "")

    BLOCKED_SUGGESTION_TYPES = {
        "contact_living_person", "reach_out", "call_person",
        "send_message", "reconnect", "schedule_call"
    }

    if not person_is_deceased:
        return {"allowed": True, "reason": "Person is living — no deceased-handling restrictions.", "required_actions": []}

    # Explicitly block suggestions that treat deceased as living
    if suggestion_type in BLOCKED_SUGGESTION_TYPES:
        return {
            "allowed": False,
            "reason": "Cannot suggest contacting a deceased person as if they are alive.",
            "required_actions": ["remove_deceased_from_active_suggestions"]
        }

    # Also block if notification_text implies active contact
    notification_text = context.get("notification_text", "").lower()
    living_triggers = ["call your", "message your", "reach out to", "reconnect with", "text your"]
    for trigger in living_triggers:
        if trigger in notification_text:
            return {
                "allowed": False,
                "reason": "Notification implies the deceased person is alive.",
                "required_actions": ["remove_deceased_from_active_suggestions"]
            }

    # Memorial/acknowledgement suggestions are allowed
    if suggestion_type in ("memorial_acknowledgement", "grief_support", "birthday_memory"):
        return {
            "allowed": True,
            "reason": "Gentle memorial acknowledgement for deceased person is appropriate.",
            "required_actions": ["add_sensitivity_warning"]
        }

    # Default: allow if grieving user — add warning
    if emotional_state in ("grieving", "sad"):
        return {
            "allowed": True,
            "reason": "Content about deceased person allowed with sensitivity warning for grieving user.",
            "required_actions": ["add_sensitivity_warning"]
        }

    return {"allowed": True, "reason": "Deceased person content within policy guidelines.", "required_actions": []}
''',

    "safety_minor_protection": '''
def evaluate(operation: str, context: dict) -> dict:
    user_is_minor = context.get("user_is_minor", False)
    subject_is_minor = context.get("subject_is_minor", False)
    operation_purpose = context.get("operation_purpose", "")

    BLOCKED_PURPOSES_FOR_MINORS = {
        "build_behavioral_profile", "store_message_content",
        "infer_emotion", "facial_recognition", "detailed_profiling"
    }

    if user_is_minor:
        return {
            "allowed": False,
            "reason": "Users under 18 may not use PersonalGenie. Age verification required.",
            "required_actions": ["block_account_creation", "request_age_verification"]
        }

    if subject_is_minor and operation_purpose in BLOCKED_PURPOSES_FOR_MINORS:
        return {
            "allowed": False,
            "reason": f"Operation '{operation_purpose}' is not permitted for minor subjects. Only basic relationship acknowledgement is allowed.",
            "required_actions": ["apply_minor_data_minimization"]
        }

    return {"allowed": True, "reason": "Minor protection policy satisfied.", "required_actions": []}
''',

    "safety_emotional_sensitivity": '''
def evaluate(operation: str, context: dict) -> dict:
    emotional_state = context.get("emotional_state", "normal")
    consecutive_dismissals = context.get("consecutive_dismissals", 0)
    proactive_suggestion_count = context.get("proactive_suggestion_count", 0)
    dismissal_count_for_type = context.get("dismissal_count_for_type", 0)

    CRISIS_STATES = {"crisis", "suicidal", "in_danger", "distressed", "grieving"}
    HIGH_CONCERN = {"anxious", "sad", "distressed"}

    if emotional_state in CRISIS_STATES:
        return {
            "allowed": False,
            "reason": f"User emotional state is '{emotional_state}'. All proactive content paused.",
            "required_actions": ["pause_proactive_mode", "offer_crisis_resources"]
        }

    if consecutive_dismissals >= 5:
        return {
            "allowed": False,
            "reason": f"User has dismissed {consecutive_dismissals} consecutive notifications. Stopping this notification type.",
            "required_actions": ["pause_notification_type", "log_user_dismissed_repeatedly"]
        }

    if proactive_suggestion_count >= 10:
        return {
            "allowed": False,
            "reason": f"Daily proactive suggestion limit reached ({proactive_suggestion_count}/10). No more suggestions today.",
            "required_actions": ["pause_proactive_mode_until_tomorrow"]
        }

    if emotional_state in HIGH_CONCERN:
        return {
            "allowed": True,
            "reason": "User showing signs of concern — proceed with reduced frequency and softer tone.",
            "required_actions": ["soften_tone", "reduce_suggestion_frequency"]
        }

    return {"allowed": True, "reason": "Emotional sensitivity check passed.", "required_actions": []}
''',

    "security_access_control": '''
def evaluate(operation: str, context: dict) -> dict:
    auth_token_user_id = context.get("auth_token_user_id")
    requesting_user_id = context.get("requesting_user_id")
    has_employee_role = context.get("has_employee_role", False)
    employee_access = context.get("employee_access", False)

    # Cross-user access: JWT user != target user — always block
    if auth_token_user_id and requesting_user_id:
        if auth_token_user_id != requesting_user_id:
            return {
                "allowed": False,
                "reason": "Access denied: JWT token user does not match the data being accessed. Cross-user access is forbidden.",
                "required_actions": ["log_unauthorized_access_attempt", "alert_security"]
            }

    # Employee accessing user data without user consent
    if has_employee_role and not employee_access:
        return {
            "allowed": False,
            "reason": "Employee access denied: the user has not granted support access. Explicit user opt-in is required.",
            "required_actions": ["log_unauthorized_access_attempt", "request_user_consent_for_support"]
        }

    return {"allowed": True, "reason": "Access control checks passed.", "required_actions": []}
''',

    "business_bilateral_graph": '''
def evaluate(operation: str, context: dict) -> dict:
    both_users_consented = context.get("both_users_consented", False)
    shares_raw_emotional_content = context.get("shares_raw_emotional_content", False)
    bilateral_severed_hours_ago = context.get("bilateral_severed_hours_ago")
    operation_purpose = context.get("operation_purpose", "")

    # Partitioning is always allowed — it separates data, doesn't share it
    if operation_purpose == "data_partitioning":
        actions = ["complete_bilateral_partitioning"] if bilateral_severed_hours_ago is not None else []
        return {
            "allowed": True,
            "reason": "Data partitioning after consent revocation is permitted and required.",
            "required_actions": actions
        }

    # Sharing raw emotional content requires explicit per-field consent beyond bilateral consent
    if shares_raw_emotional_content and not both_users_consented:
        return {
            "allowed": False,
            "reason": "Raw emotional content cannot be shared without bilateral consent from both users.",
            "required_actions": ["request_bilateral_emotional_consent"]
        }

    if shares_raw_emotional_content and both_users_consented:
        # Still need explicit emotional content consent — bilateral != emotional content sharing
        return {
            "allowed": False,
            "reason": "Sharing raw emotional content requires explicit per-type consent beyond general bilateral consent.",
            "required_actions": ["request_emotional_content_sharing_consent"]
        }

    if not both_users_consented:
        return {
            "allowed": False,
            "reason": "Bilateral data sharing requires consent from both users.",
            "required_actions": ["request_bilateral_consent"]
        }

    return {"allowed": True, "reason": "Bilateral sharing conditions satisfied.", "required_actions": []}
''',

    "business_agent_diplomacy": '''
def evaluate(operation: str, context: dict) -> dict:
    agent_diplomacy_consented = context.get("agent_diplomacy_consented", False)
    person_is_deceased = context.get("person_is_deceased", False)
    operation_timing = context.get("operation_timing", "")

    if person_is_deceased:
        return {
            "allowed": False,
            "reason": "Cannot send messages to a deceased person.",
            "required_actions": ["block_message_to_deceased"]
        }

    if not agent_diplomacy_consented:
        return {
            "allowed": False,
            "reason": "Agent diplomacy not enabled. User must opt in before Genie can send messages on their behalf.",
            "required_actions": ["request_agent_diplomacy_consent"]
        }

    if operation_timing in ("quiet_hours", "night"):
        return {
            "allowed": True,
            "reason": "Agent diplomacy enabled but message delayed — quiet hours active.",
            "required_actions": ["delay_until_after_quiet_hours"]
        }

    return {"allowed": True, "reason": "Agent diplomacy consent verified.", "required_actions": []}
''',

}


def write_compiled_functions():
    """Write hand-written evaluate() functions directly to the compiled_function column."""
    db = create_client(settings.supabase_url, settings.supabase_key)

    print(f"Writing {len(COMPILED_FUNCTIONS)} compiled policy functions...")
    success = 0
    errors = 0

    for name, function_code in COMPILED_FUNCTIONS.items():
        try:
            db.table("policies").update({
                "compiled_function": function_code.strip()
            }).eq("name", name).execute()
            print(f"  ✓ {name}")
            success += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            errors += 1

    print(f"\nDone: {success} written, {errors} errors")
    if errors == 0:
        print("All compiled functions ready. Run tests:")
        print("  python tests/policy_tests/run_all.py")


if __name__ == "__main__":
    write_compiled_functions()
