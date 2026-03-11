"""
routers/billing.py — Stripe subscription management.

Tiers:
  Free       — limited to 3 people in graph, no health tracking, no rules
  Individual — $9.99/month — full personal features
  Family     — $14.99/month — up to 4 family members, shared moments
  Pro        — $24.99/month — unlimited everything + early access features

Uses Stripe Checkout for payment flow.
Webhooks update subscription status in the subscriptions table.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import get_settings
from routers.auth import verify_app_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])

# ── Plan definitions ──────────────────────────────────────────────────────────

_PLANS = [
    {
        "id": "free",
        "name": "Free",
        "price_monthly": 0.00,
        "features": [
            "Up to 3 people in your relationship graph",
            "Daily Genie moments",
            "WhatsApp interface",
        ],
        "stripe_price_id": None,
    },
    {
        "id": "individual",
        "name": "Individual",
        "price_monthly": 9.99,
        "features": [
            "Unlimited people in your graph",
            "Health & nutrition tracking",
            "Custom Genie rules",
            "Training session capture",
            "Nightly conversations",
            "Full relationship intelligence",
        ],
        "stripe_price_id": "__individual__",   # replaced at runtime from settings
    },
    {
        "id": "family",
        "name": "Family",
        "price_monthly": 14.99,
        "features": [
            "Everything in Individual",
            "Up to 4 family members",
            "Shared moments and milestones",
            "Family relationship graph",
        ],
        "stripe_price_id": "__family__",
    },
    {
        "id": "pro",
        "name": "Pro",
        "price_monthly": 24.99,
        "features": [
            "Everything in Family",
            "Unlimited family members",
            "Early access to new features",
            "Priority support",
            "Advanced analytics",
        ],
        "stripe_price_id": "__pro__",
    },
]


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_user_id(request: Request) -> str:
    token = request.headers.get("X-App-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-App-Token")
    payload = verify_app_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]


# ── Pydantic models ───────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    user_id: str
    plan: str                  # "individual" | "family" | "pro"
    success_url: str
    cancel_url: str


class PortalRequest(BaseModel):
    user_id: str
    return_url: str


# ── Stripe helpers ────────────────────────────────────────────────────────────

def _get_stripe():
    """Return configured stripe module or raise if not configured."""
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing is not configured on this server.")
    try:
        import stripe
        stripe.api_key = settings.stripe_secret_key
        return stripe
    except ImportError:
        raise HTTPException(status_code=503, detail="stripe library is not installed.")


def _get_or_create_stripe_customer(user_id: str, stripe) -> str:
    """
    Return the Stripe customer ID for a user, creating one if it doesn't exist.
    Stores/reads from the subscriptions table.
    """
    from db import get_db
    supabase = get_db()

    result = (
        supabase.table("subscriptions")
        .select("stripe_customer_id")
        .eq("user_id", user_id)
        .execute()
    )
    if result.data and result.data[0].get("stripe_customer_id"):
        return result.data[0]["stripe_customer_id"]

    # Look up user email/name for the Stripe customer record
    user_result = supabase.table("users").select("name, phone").eq("id", user_id).execute()
    user = user_result.data[0] if user_result.data else {}

    customer = stripe.Customer.create(
        name=user.get("name", ""),
        phone=user.get("phone", ""),
        metadata={"genie_user_id": user_id},
    )

    # Upsert a free subscription row with the customer ID
    supabase.table("subscriptions").upsert(
        {
            "user_id": user_id,
            "stripe_customer_id": customer["id"],
            "plan": "free",
            "status": "active",
        },
        on_conflict="user_id",
    ).execute()

    return customer["id"]


def _price_id_for_plan(plan: str) -> str:
    """Return the Stripe price ID for a plan from settings."""
    settings = get_settings()
    mapping = {
        "individual": settings.stripe_price_individual,
        "family": settings.stripe_price_family,
        "pro": settings.stripe_price_pro,
    }
    price_id = mapping.get(plan, "")
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail=f"No Stripe price configured for plan '{plan}'. Set stripe_price_{plan} in settings.",
        )
    return price_id


def _plan_from_price_id(price_id: str) -> str:
    """Reverse map: Stripe price ID → plan name. Falls back to 'individual'."""
    settings = get_settings()
    mapping = {
        settings.stripe_price_individual: "individual",
        settings.stripe_price_family: "family",
        settings.stripe_price_pro: "pro",
    }
    return mapping.get(price_id, "individual")


# ── Public helper (importable by other services for paywall checks) ───────────

def get_user_plan(user_id: str) -> str:
    """
    Return the current plan for a user: "free" | "individual" | "family" | "pro".
    Falls back to "free" if no subscription record exists or on any error.
    Can be imported by other modules for paywall checks.
    """
    try:
        from db import get_db
        supabase = get_db()
        result = (
            supabase.table("subscriptions")
            .select("plan, status")
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return "free"
        row = result.data[0]
        # Only honor active / trialing subscriptions
        if row.get("status") in ("active", "trialing"):
            return row.get("plan", "free")
        return "free"
    except Exception as exc:
        logger.error("get_user_plan failed for %s: %s", user_id, exc)
        return "free"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/plans")
async def list_plans():
    """
    Return all available plans with pricing and features.
    No auth required — used on the marketing / paywall screens.
    """
    settings = get_settings()
    plans = []
    for p in _PLANS:
        plan = dict(p)
        # Replace placeholder with real price ID from settings (without leaking secret key)
        if plan["id"] == "individual":
            plan["stripe_price_id"] = settings.stripe_price_individual or None
        elif plan["id"] == "family":
            plan["stripe_price_id"] = settings.stripe_price_family or None
        elif plan["id"] == "pro":
            plan["stripe_price_id"] = settings.stripe_price_pro or None
        plans.append(plan)
    return {"plans": plans}


@router.post("/checkout")
async def create_checkout(request: Request, body: CheckoutRequest):
    """
    Create a Stripe Checkout session for a plan upgrade.
    Returns {checkout_url} — the iOS app opens this in a browser/SafariVC.
    """
    _get_user_id(request)  # auth check

    if body.plan not in ("individual", "family", "pro"):
        raise HTTPException(status_code=400, detail="plan must be 'individual', 'family', or 'pro'")

    stripe = _get_stripe()
    price_id = _price_id_for_plan(body.plan)
    customer_id = _get_or_create_stripe_customer(body.user_id, stripe)

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            metadata={"genie_user_id": body.user_id, "plan": body.plan},
            subscription_data={"metadata": {"genie_user_id": body.user_id, "plan": body.plan}},
        )
    except Exception as exc:
        logger.error("Stripe checkout failed for user %s: %s", body.user_id, exc)
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")

    return {"checkout_url": session.url}


@router.get("/subscription/{user_id}")
async def get_subscription(user_id: str, request: Request):
    """Return the current subscription status for a user."""
    _get_user_id(request)  # auth check

    try:
        from db import get_db
        supabase = get_db()
        result = (
            supabase.table("subscriptions")
            .select("plan, status, current_period_end, cancel_at_period_end")
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return {
                "plan": "free",
                "status": "active",
                "current_period_end": None,
                "cancel_at_period_end": False,
            }
        row = result.data[0]
        return {
            "plan": row.get("plan", "free"),
            "status": row.get("status", "active"),
            "current_period_end": row.get("current_period_end"),
            "cancel_at_period_end": row.get("cancel_at_period_end", False),
        }
    except Exception as exc:
        logger.error("Failed to fetch subscription for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Could not fetch subscription")


@router.post("/portal")
async def create_portal(request: Request, body: PortalRequest):
    """
    Create a Stripe Customer Portal session so the user can manage their subscription.
    Returns {portal_url}.
    """
    _get_user_id(request)  # auth check

    stripe = _get_stripe()
    customer_id = _get_or_create_stripe_customer(body.user_id, stripe)

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=body.return_url,
        )
    except Exception as exc:
        logger.error("Stripe portal failed for user %s: %s", body.user_id, exc)
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")

    return {"portal_url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint — no auth, but signature is verified with the
    stripe_webhook_secret setting.

    Handles:
    - checkout.session.completed       → activate subscription
    - customer.subscription.updated    → update plan / status
    - customer.subscription.deleted    → downgrade to free
    - invoice.payment_failed           → mark as past_due
    """
    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        import stripe
        stripe.api_key = settings.stripe_secret_key

        if settings.stripe_webhook_secret:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
        else:
            # Dev fallback: parse without verifying signature
            import json
            event = json.loads(payload)
            logger.warning("stripe_webhook_secret not set — skipping signature verification")

    except Exception as exc:
        logger.error("Stripe webhook signature error: %s", exc)
        raise HTTPException(status_code=400, detail=f"Webhook error: {exc}")

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    from db import get_db
    supabase = get_db()

    try:
        if event_type == "checkout.session.completed":
            genie_user_id = data.get("metadata", {}).get("genie_user_id")
            plan = data.get("metadata", {}).get("plan", "individual")
            subscription_id = data.get("subscription")
            customer_id = data.get("customer")

            if genie_user_id and subscription_id:
                # Fetch subscription details from Stripe for period info
                sub = stripe.Subscription.retrieve(subscription_id)
                supabase.table("subscriptions").upsert(
                    {
                        "user_id": genie_user_id,
                        "stripe_customer_id": customer_id,
                        "stripe_subscription_id": subscription_id,
                        "plan": plan,
                        "status": sub.get("status", "active"),
                        "current_period_start": _ts(sub.get("current_period_start")),
                        "current_period_end": _ts(sub.get("current_period_end")),
                        "cancel_at_period_end": sub.get("cancel_at_period_end", False),
                        "updated_at": "now()",
                    },
                    on_conflict="user_id",
                ).execute()
                logger.info("Checkout completed: user=%s plan=%s", genie_user_id, plan)

        elif event_type == "customer.subscription.updated":
            subscription_id = data.get("id")
            customer_id = data.get("customer")
            status = data.get("status", "active")
            cancel_at_period_end = data.get("cancel_at_period_end", False)
            current_period_start = _ts(data.get("current_period_start"))
            current_period_end = _ts(data.get("current_period_end"))

            # Determine plan from price ID
            items = data.get("items", {}).get("data", [])
            price_id = items[0]["price"]["id"] if items else ""
            plan = _plan_from_price_id(price_id) if price_id else None

            update_fields = {
                "status": status,
                "cancel_at_period_end": cancel_at_period_end,
                "current_period_start": current_period_start,
                "current_period_end": current_period_end,
                "updated_at": "now()",
            }
            if plan:
                update_fields["plan"] = plan

            (
                supabase.table("subscriptions")
                .update(update_fields)
                .eq("stripe_subscription_id", subscription_id)
                .execute()
            )
            logger.info("Subscription updated: id=%s status=%s plan=%s", subscription_id, status, plan)

        elif event_type == "customer.subscription.deleted":
            subscription_id = data.get("id")
            (
                supabase.table("subscriptions")
                .update({"plan": "free", "status": "canceled", "updated_at": "now()"})
                .eq("stripe_subscription_id", subscription_id)
                .execute()
            )
            logger.info("Subscription deleted: id=%s — downgraded to free", subscription_id)

        elif event_type == "invoice.payment_failed":
            subscription_id = data.get("subscription")
            if subscription_id:
                (
                    supabase.table("subscriptions")
                    .update({"status": "past_due", "updated_at": "now()"})
                    .eq("stripe_subscription_id", subscription_id)
                    .execute()
                )
                logger.info("Payment failed for subscription %s — marked past_due", subscription_id)

    except Exception as exc:
        logger.error("Webhook handler error for event %s: %s", event_type, exc)
        # Return 200 anyway so Stripe doesn't retry — the error is logged
        return {"status": "logged_error"}

    return {"status": "ok"}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ts(unix_ts) -> Optional[str]:
    """Convert a Unix timestamp integer to an ISO 8601 string, or None."""
    if unix_ts is None:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).isoformat()
    except Exception:
        return None
