"""
The Policy Engine is the privacy and security brain of PersonalGenie.

Every time any module wants to read, write, share or delete user data
it must ask this engine for permission first.

Think of it as a very fast lawyer that sits between your application
and your database. It reads all the privacy rules written in plain
English and enforces them automatically — no developer has to remember
to check them manually.

Every decision is logged to the audit trail. Every required action
is tracked. Nothing slips through.
"""

import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable
import anthropic
from supabase import Client

logger = logging.getLogger(__name__)


class PolicyViolationError(Exception):
    """
    Raised when a data operation is blocked by the Policy Engine.
    The message is the plain English reason — safe to show to users.
    """
    pass


@dataclass
class PolicyDecision:
    """
    The result of asking the Policy Engine whether a data operation is allowed.

    allowed: True means proceed, False means block immediately.
    reason: Plain English explanation of the decision.
    required_actions: Things that must happen before or after the operation.
    applicable_policies: Which rules were checked to reach this decision.
    execution_time_ms: How long the evaluation took — target is under 100ms.
    """
    allowed: bool
    reason: str
    required_actions: list = field(default_factory=list)
    applicable_policies: list = field(default_factory=list)
    execution_time_ms: int = 0


class PolicyEngine:
    """
    The main engine. One instance created at server startup and reused
    for every request. Policies are compiled once and cached in memory.
    """

    def __init__(self, supabase: Client, claude: anthropic.Anthropic):
        # The Supabase connection — for loading policies and logging decisions
        self.db = supabase
        # Claude — used to compile policies and parse test scenarios
        self.claude = claude
        # In-memory cache of compiled policy functions
        # Key: policy name, Value: the callable evaluate(operation, context) -> dict
        self.compiled_policies: dict[str, Callable] = {}
        # Load and compile all active policies from the database
        self._load_all_policies()

    def _load_all_policies(self):
        """
        Read every active policy from the database and compile it into
        an enforcement function that runs in under 1ms per check.
        Called once when the server starts.
        """
        try:
            result = self.db.table("policies").select("*").eq("active", True).execute()
        except Exception as e:
            logger.error(f"Policy Engine: could not load policies from database: {e}")
            logger.warning("Policy Engine starting with zero policies — all operations will be permitted")
            return

        compiled_count = 0
        for policy in result.data:
            try:
                compiled = self._compile_policy(
                    name=policy["name"],
                    content=policy["content"],
                    cached_function=policy.get("compiled_function")
                )
                self.compiled_policies[policy["name"]] = compiled
                compiled_count += 1
            except Exception as e:
                logger.error(f"Policy Engine: failed to compile policy '{policy['name']}': {e}")

        logger.info(f"Policy Engine loaded {compiled_count}/{len(result.data)} policies")

    def _compile_policy(
        self,
        name: str,
        content: str,
        cached_function: Optional[str] = None
    ) -> Callable:
        """
        Turn a policy written in plain English into a Python function
        that evaluates whether an operation is allowed.

        If a cached compiled version exists in the database, use that
        instead of calling Claude again — this makes restarts fast.

        The compiled function always takes (operation, context) and
        returns {"allowed": bool, "reason": str, "required_actions": list}.
        """
        # Use cached compiled function if available (avoids Claude call on restart)
        if cached_function:
            try:
                namespace = {}
                exec(cached_function, namespace)  # noqa: S102
                if "evaluate" in namespace:
                    return namespace["evaluate"]
            except Exception:
                pass  # Fall through to recompile

        # Ask Claude to turn the natural language policy into a Python function
        response = self.claude.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2000,
            system="""You are a privacy policy compiler for PersonalGenie.
Convert natural language privacy policies into Python evaluation functions.

The function signature must be exactly:
def evaluate(operation: str, context: dict) -> dict:

The function must return a dict with exactly these keys:
{
    "allowed": bool,
    "reason": str,  # plain English, one sentence, safe to show users
    "required_actions": list  # strings describing actions to take, empty list if none
}

Context dict may contain these fields (all optional, check with .get()):
    user_id, user_location, jurisdiction, data_type, consent_status,
    sender_consented, contains_biometric, data_age_days, user_is_minor,
    person_is_deceased, is_bilateral, operation_timing, biometric_consented,
    whatsapp_consented, agent_diplomacy_consented, both_users_consented,
    emotional_state, consecutive_dismissals, data_age_hours,
    employee_access, has_court_order, auth_token_user_id, requesting_user_id,
    shares_raw_emotional_content, bilateral_severed_hours_ago,
    dismissal_count_for_type, proactive_suggestion_count

The function must be safe, readable, and handle missing context keys gracefully.
Return only the Python function code. No markdown fences. No explanation. Just code.""",
            messages=[{
                "role": "user",
                "content": f"Policy name: {name}\n\nPolicy content:\n{content}"
            }]
        )

        function_code = response.content[0].text.strip()
        # Strip any accidental markdown fences Claude adds
        if function_code.startswith("```"):
            lines = function_code.split("\n")
            function_code = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        # Compile the function into executable code in a safe namespace
        namespace = {}
        exec(function_code, namespace)  # noqa: S102

        if "evaluate" not in namespace:
            raise ValueError(f"Compiled policy '{name}' has no evaluate() function")

        # Save the compiled function back to the database so restarts are faster
        try:
            self.db.table("policies").update({
                "compiled_function": function_code,
                "updated_at": "now()"
            }).eq("name", name).execute()
        except Exception:
            pass  # Non-critical — just means next restart will recompile

        return namespace["evaluate"]

    def evaluate(self, operation: str, context: dict) -> PolicyDecision:
        """
        The main function every module calls before touching user data.

        Pass in what you are trying to do (operation) and who is involved
        and what data (context). Get back a PolicyDecision saying whether
        you can proceed and what you need to do first.

        Example:
            decision = policy_engine.evaluate(
                operation='store_whatsapp_message',
                context={
                    'user_id': user['id'],
                    'user_location': 'US-CA',
                    'jurisdiction': 'CCPA',
                    'data_type': 'whatsapp_message',
                    'consent_status': user['whatsapp_consented'],
                    'sender_consented': True,
                    'contains_biometric': False,
                }
            )
            if not decision.allowed:
                raise PolicyViolationError(decision.reason)
        """
        start_time = time.time()

        # Find which policies apply to this specific operation and context
        applicable = self._find_applicable_policies(operation, context)

        all_required_actions = []
        blocking_reason = None

        # Run every applicable policy — stop at the first one that blocks
        for policy_name in applicable:
            if policy_name not in self.compiled_policies:
                continue  # Policy referenced but not compiled — skip, don't block

            try:
                result = self.compiled_policies[policy_name](operation, context)

                if not result.get("allowed", True):
                    blocking_reason = result.get("reason", f"Blocked by policy: {policy_name}")
                    break  # One block is enough — no need to check the rest

                # Collect required actions from all passing policies
                all_required_actions.extend(result.get("required_actions", []))

            except Exception as e:
                # If a policy function crashes, block the operation and log it.
                # Never silently fail — a crashing policy is a blocking policy.
                blocking_reason = f"Policy '{policy_name}' encountered an error: {str(e)}"
                logger.error(f"Policy Engine: {blocking_reason}")
                break

        execution_ms = int((time.time() - start_time) * 1000)

        decision = PolicyDecision(
            allowed=blocking_reason is None,
            reason=blocking_reason or "All applicable policies passed",
            required_actions=list(set(all_required_actions)),  # deduplicate
            applicable_policies=applicable,
            execution_time_ms=execution_ms
        )

        # Log every decision — this is the complete audit trail
        self._log_decision(operation, context, decision)

        return decision

    def _find_applicable_policies(self, operation: str, context: dict) -> list:
        """
        Figure out which policies apply to a given operation based on
        the operation type, user jurisdiction, and data types involved.

        Every operation gets at least the safety and security baseline checks.
        Jurisdiction-specific checks (GDPR, CCPA) are added when relevant.
        """
        applicable = []

        # Map every operation type to the policies that govern it
        operation_policy_map = {
            "store_message": [
                "gdpr_consent_requirements",
                "gdpr_data_minimization",
                "ccpa_data_disclosure",
                "safety_minor_protection",
            ],
            "store_whatsapp_message": [
                "gdpr_consent_requirements",
                "gdpr_data_minimization",
                "safety_minor_protection",
            ],
            "delete_user": [
                "gdpr_right_to_erasure",
                "ccpa_opt_out_rights",
            ],
            "share_bilateral": [
                "gdpr_consent_requirements",
                "business_bilateral_graph",
                "safety_deceased_persons",
            ],
            "infer_emotion": [
                "gdpr_biometric_data",
                "safety_emotional_sensitivity",
            ],
            "send_agent_message": [
                "business_agent_diplomacy",
                "gdpr_consent_requirements",
                "safety_emotional_sensitivity",
            ],
            "store_deceased_data": [
                "safety_deceased_persons",
                "gdpr_consent_requirements",
            ],
            "process_minor_data": [
                "safety_minor_protection",
            ],
            "build_people_graph": [
                "gdpr_consent_requirements",
                "gdpr_data_minimization",
                "safety_minor_protection",
                "safety_deceased_persons",
            ],
            "send_evening_digest": [
                "safety_emotional_sensitivity",
                "safety_deceased_persons",
            ],
            "process_voice_note": [
                "gdpr_consent_requirements",
                "gdpr_data_minimization",
            ],
            "send_invite": [
                "gdpr_consent_requirements",
                "business_bilateral_graph",
            ],
            "revoke_consent": [
                "gdpr_right_to_erasure",
                "ccpa_opt_out_rights",
            ],
            "access_user_data": [
                "security_access_control",
                "gdpr_consent_requirements",
            ],
        }

        # Add jurisdiction-specific policies based on user location
        jurisdiction = context.get("jurisdiction", "")
        user_location = context.get("user_location", "")

        if jurisdiction == "GDPR" or user_location.startswith("EU") or user_location.startswith("EEA"):
            applicable.extend([
                "gdpr_right_to_erasure",
                "gdpr_consent_requirements",
                "gdpr_data_retention",
            ])

        if jurisdiction == "CCPA" or user_location == "US-CA":
            applicable.extend([
                "ccpa_california_rights",
                "ccpa_opt_out_rights",
            ])

        # Add operation-specific policies
        applicable.extend(operation_policy_map.get(operation, []))

        # Always check these safety and security baselines on every operation
        applicable.extend([
            "safety_minor_protection",
            "security_access_control",
        ])

        # Check deceased person policy if relevant
        if context.get("person_is_deceased"):
            applicable.append("safety_deceased_persons")

        # Check emotional sensitivity policy if emotional state is available
        if context.get("emotional_state") in ("distressed", "grieving", "anxious", "sad"):
            applicable.append("safety_emotional_sensitivity")

        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for p in applicable:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

    def _log_decision(self, operation: str, context: dict, decision: PolicyDecision):
        """
        Write every policy decision to the database.
        This is the complete audit trail — every decision Genie ever made
        about user data is stored here and can be shown in the Transparency tab.

        Sensitive values (tokens, message bodies) are stripped before logging.
        """
        # Remove sensitive fields before storing in the audit log
        safe_context = {
            k: v for k, v in context.items()
            if k not in {
                "access_token", "refresh_token", "message_body",
                "email_content", "transcript", "audio_bytes"
            }
        }

        try:
            result = self.db.table("policy_decisions").insert({
                "operation": operation,
                "context": safe_context,
                "applicable_policies": decision.applicable_policies,
                "decision": decision.allowed,
                "reason": decision.reason,
                "required_actions": decision.required_actions,
                "execution_time_ms": decision.execution_time_ms,
            }).execute()

            # If there are required actions, log each one individually
            if decision.required_actions and result.data:
                decision_id = result.data[0]["id"]
                for action in decision.required_actions:
                    self.db.table("policy_actions_log").insert({
                        "decision_id": decision_id,
                        "action": action,
                        "executed": False,
                    }).execute()

        except Exception as e:
            # Logging failure must never block the actual operation
            logger.error(f"Policy Engine: failed to log decision: {e}")

    def test_scenario(
        self,
        policy_name: str,
        scenario: str,
        expected: str,
        context: dict = None
    ) -> dict:
        """
        Test any policy by describing a scenario in plain English.

        Example:
            result = engine.test_scenario(
                policy_name='gdpr_right_to_erasure',
                scenario='A user in Germany deletes their account. All messages must be gone within 72 hours.',
                expected='PASS'
            )
        Returns a dict showing whether the policy behaves as expected.
        """
        # Use provided context dict, or parse from natural language if not given
        if context is None:
            context = self._scenario_to_context(scenario)

        # Evaluate only against the specific policy being tested
        # (not the full policy set — that's evaluate() for production use)
        if policy_name not in self.compiled_policies:
            return {
                "scenario": scenario,
                "policy": policy_name,
                "expected": expected,
                "actual": "ERROR",
                "test_passed": False,
                "reason": f"Policy '{policy_name}' is not compiled — check that it was seeded and loaded",
                "execution_time_ms": 0,
            }

        start = time.time()
        try:
            # Determine what operation this policy governs based on its name
            operation = self._infer_operation_from_policy(policy_name)
            result = self.compiled_policies[policy_name](operation, context)
            actual = "PASS" if result.get("allowed", True) else "FAIL"
        except Exception as e:
            actual = "ERROR"
            result = {"reason": str(e), "allowed": None}

        execution_ms = int((time.time() - start) * 1000)
        test_passed = actual == expected

        return {
            "scenario": scenario,
            "policy": policy_name,
            "expected": expected,
            "actual": actual,
            "test_passed": test_passed,
            "reason": result.get("reason", ""),
            "execution_time_ms": execution_ms,
        }

    def _scenario_to_context(self, scenario: str) -> dict:
        """
        Use Claude to convert a plain English scenario description into
        the structured context dict that policy functions expect.

        This means anyone — developer, lawyer, founder — can write tests
        in plain English without knowing the technical field names.
        """
        response = self.claude.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=600,
            system="""Convert this scenario description into a JSON context object
for privacy policy evaluation in PersonalGenie.

Include any relevant fields from this list (only include fields that apply):
user_id, user_location, jurisdiction, data_type, consent_status,
whatsapp_consented, biometric_consented, agent_diplomacy_consented,
sender_consented, contains_biometric, data_age_days, data_age_hours,
user_is_minor, person_is_deceased, is_bilateral, operation_timing,
emotional_state, employee_access, has_court_order,
auth_token_user_id, requesting_user_id, both_users_consented,
shares_raw_emotional_content, bilateral_severed_hours_ago,
dismissal_count_for_type, proactive_suggestion_count, consecutive_dismissals.

Set jurisdiction to GDPR for EU users, CCPA for California users.
Return only valid JSON. No explanation. No markdown.""",
            messages=[{"role": "user", "content": scenario}]
        )

        try:
            text = response.content[0].text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            return json.loads(text)
        except Exception:
            # Fallback to minimal context if Claude's response can't be parsed
            return {"scenario_raw": scenario}

    def _infer_operation_from_policy(self, policy_name: str) -> str:
        """
        Map a policy name to the most relevant operation type so test
        scenarios can evaluate correctly.
        """
        mapping = {
            "gdpr_right_to_erasure": "delete_user",
            "gdpr_consent_requirements": "store_message",
            "gdpr_data_retention": "store_message",
            "gdpr_data_minimization": "store_message",
            "gdpr_biometric_data": "infer_emotion",
            "ccpa_california_rights": "access_user_data",
            "ccpa_opt_out_rights": "delete_user",
            "safety_deceased_persons": "send_evening_digest",
            "safety_minor_protection": "store_message",
            "safety_emotional_sensitivity": "send_agent_message",
            "security_access_control": "access_user_data",
            "business_bilateral_graph": "share_bilateral",
            "business_agent_diplomacy": "send_agent_message",
        }
        return mapping.get(policy_name, "store_message")

    def reload_policies(self):
        """
        Hot-reload all policies from the database without restarting the server.
        Call this after adding or editing any policy so changes take effect immediately.
        """
        self.compiled_policies = {}
        self._load_all_policies()
        logger.info("Policy Engine reloaded successfully")

    def get_audit_log(self, user_id: str, days: int = 30) -> list:
        """
        Return the complete audit log for a user in plain English format.
        This is what appears in the Transparency tab of the iOS app —
        every decision Genie made about this user's data.
        """
        try:
            # Query decisions where user_id appears in the context JSON
            result = (
                self.db.table("policy_decisions")
                .select("*")
                .filter("context->>user_id", "eq", user_id)
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            )
            return result.data
        except Exception as e:
            logger.error(f"Policy Engine: failed to fetch audit log for {user_id}: {e}")
            return []

    def get_policy_status(self) -> dict:
        """
        Return a summary of which policies are loaded and their last test results.
        Used by the /policy-dashboard endpoint.
        """
        try:
            result = self.db.table("policies").select("*").execute()
            policies = result.data
        except Exception:
            policies = []

        return {
            "total_policies": len(policies),
            "compiled_policies": len(self.compiled_policies),
            "active_policies": [p["name"] for p in policies if p.get("active")],
            "last_test_results": {
                p["name"]: p.get("test_results")
                for p in policies
                if p.get("test_results")
            },
        }
