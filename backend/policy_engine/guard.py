"""
policy_engine/guard.py — Lightweight policy check interface.

Import this anywhere in the codebase. Call guard.check() before any
sensitive data operation. Raises PolicyViolationError if blocked.

Usage:
    from policy_engine.guard import check
    check('store_whatsapp_message', {'user_id': user_id, 'consent_status': True, ...})

The engine is initialized once at server startup via guard.init().
If the engine isn't initialized yet (e.g. during tests), all checks pass.
"""
import logging
from typing import Optional
from policy_engine.engine import PolicyEngine, PolicyViolationError  # noqa: F401 — re-export

logger = logging.getLogger(__name__)

_engine: Optional[PolicyEngine] = None


def init(engine: PolicyEngine) -> None:
    """Called once at server startup after PolicyEngine is initialized."""
    global _engine
    _engine = engine
    logger.info("Policy guard initialized")


def check(operation: str, context: dict) -> None:
    """
    Run a policy check. Raises PolicyViolationError if the operation is blocked.
    If the engine isn't initialized, silently passes (safe during startup/tests).
    """
    if _engine is None:
        return
    decision = _engine.evaluate(operation, context)
    if not decision.allowed:
        raise PolicyViolationError(decision.reason)


def evaluate(operation: str, context: dict):
    """
    Like check() but returns the full PolicyDecision instead of raising.
    Use this when you need to inspect required_actions.
    """
    if _engine is None:
        from policy_engine.engine import PolicyDecision
        return PolicyDecision(allowed=True, reason="Engine not initialized")
    return _engine.evaluate(operation, context)
