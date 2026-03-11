"""
services/plaid_client.py — Plaid financial data integration.

Read-only. Never writes transactions. Never initiates transfers.
Uses Plaid Link flow: create_link_token → iOS opens Link → exchange_public_token.

Token storage: financial_accounts table.
  Columns: user_id, access_token (encrypted at rest by Supabase), item_id,
           institution_name, last_synced.

Privacy policy — financial data is ONLY used for:
  1. Personal capability signals (never stored in people graph)
  2. Financial rules the user explicitly creates
  3. Never used to infer work patterns
  4. Spending summary visible in Settings → Connections → Financial
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

PLAID_SANDBOX_BASE = "https://sandbox.plaid.com"
PLAID_PRODUCTION_BASE = "https://production.plaid.com"

# ── Capability signal categories ───────────────────────────────────────────────
# Maps Plaid category strings → internal capability signal type.
# "mental_health" is handled but NEVER surfaced directly — see policy note.
CATEGORY_SIGNAL_MAP = {
    "restaurants": "social_food_interest",
    "food and drink": "social_food_interest",
    "gyms and fitness centers": "physical_capability",
    "sports": "physical_capability",
    "recreation": "physical_capability",
    "bookstores": "intellectual_signal",
    "books": "intellectual_signal",
    "education": "intellectual_signal",
    "airlines": "travel_interest",
    "hotels and motels": "travel_interest",
    "travel": "travel_interest",
    "car rental": "travel_interest",
    "mental health": "emotional_capability",       # PRIVATE — never surfaced directly
    "therapy": "emotional_capability",             # PRIVATE — never surfaced directly
    "counseling": "emotional_capability",          # PRIVATE — never surfaced directly
}

SENSITIVE_SIGNALS = {"emotional_capability"}  # never returned in API responses


class PlaidClient:
    """
    Per-user Plaid client.

    Usage:
        client = PlaidClient(user_id)
        link_token = await client.create_link_token()
        # iOS opens Plaid Link with link_token, gets back public_token
        await client.exchange_public_token(public_token)
        transactions = await client.get_transactions(days=30)
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._settings = get_settings()
        self._base_url = (
            PLAID_PRODUCTION_BASE
            if self._settings.plaid_env == "production"
            else PLAID_SANDBOX_BASE
        )

    # ── HTTP helper ───────────────────────────────────────────────────────────

    async def _post(self, path: str, body: dict) -> dict:
        """POST to Plaid API with client credentials injected."""
        payload = {
            "client_id": self._settings.plaid_client_id,
            "secret": self._settings.plaid_secret,
            **body,
        }
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(f"{self._base_url}{path}", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ── Token management ──────────────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        """Load the access token from DB. Raises if not connected."""
        try:
            import database as db_mod
            db = db_mod.get_db()
            row = (
                db.table("financial_accounts")
                .select("access_token")
                .eq("user_id", self.user_id)
                .single()
                .execute()
            )
            if row.data and row.data.get("access_token"):
                return row.data["access_token"]
        except Exception as exc:
            logger.warning("Could not load Plaid token for %s: %s", self.user_id, exc)
        raise RuntimeError(f"No Plaid connection for user {self.user_id}")

    async def _save_connection(
        self,
        access_token: str,
        item_id: str,
        institution_name: str = "",
    ) -> None:
        try:
            import database as db_mod
            db = db_mod.get_db()
            db.table("financial_accounts").upsert({
                "id": str(uuid.uuid4()),
                "user_id": self.user_id,
                "access_token": access_token,
                "item_id": item_id,
                "institution_name": institution_name,
                "last_synced": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="user_id").execute()
        except Exception as exc:
            logger.error("Could not save Plaid connection for %s: %s", self.user_id, exc)
            raise

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_link_token(self) -> str:
        """
        Create a Plaid Link token for the iOS app to initiate the Link flow.
        Returns the link_token string.
        """
        data = await self._post("/link/token/create", {
            "user": {"client_user_id": self.user_id},
            "client_name": "Personal Genie",
            "products": ["transactions"],
            "country_codes": ["US"],
            "language": "en",
        })
        return data["link_token"]

    async def exchange_public_token(self, public_token: str) -> None:
        """
        Exchange the public_token from Plaid Link for a permanent access_token.
        Saves the connection to the financial_accounts table.
        """
        data = await self._post("/item/public_token/exchange", {
            "public_token": public_token,
        })
        access_token = data["access_token"]
        item_id = data["item_id"]

        # Fetch institution name from the item metadata
        institution_name = ""
        try:
            item_data = await self._post("/item/get", {"access_token": access_token})
            institution_id = item_data.get("item", {}).get("institution_id", "")
            if institution_id:
                inst_data = await self._post("/institutions/get_by_id", {
                    "institution_id": institution_id,
                    "country_codes": ["US"],
                })
                institution_name = inst_data.get("institution", {}).get("name", "")
        except Exception as exc:
            logger.warning("Could not fetch institution name: %s", exc)

        await self._save_connection(access_token, item_id, institution_name)

    async def get_transactions(self, days: int = 30) -> list[dict]:
        """
        Fetch recent transactions. Returns a list of dicts with standardized fields.
        Categories are mapped to capability signals where applicable.
        """
        access_token = await self._get_access_token()
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        data = await self._post("/transactions/get", {
            "access_token": access_token,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "options": {"count": 500, "offset": 0},
        })

        transactions = []
        for txn in data.get("transactions", []):
            categories = [c.lower() for c in (txn.get("category") or [])]
            capability_signal = self._map_to_signal(categories)
            transactions.append({
                "id": txn.get("transaction_id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "name": txn.get("name"),
                "merchant_name": txn.get("merchant_name"),
                "categories": txn.get("category", []),
                "capability_signal": capability_signal,
                # Never include raw account numbers
            })

        # Update last_synced
        try:
            import database as db_mod
            db_mod.get_db().table("financial_accounts").update({
                "last_synced": datetime.now(timezone.utc).isoformat()
            }).eq("user_id", self.user_id).execute()
        except Exception:
            pass

        return transactions

    async def get_accounts(self) -> list[dict]:
        """
        Fetch linked accounts (balances and account types).
        Does NOT return account numbers.
        """
        access_token = await self._get_access_token()
        data = await self._post("/accounts/get", {"access_token": access_token})
        accounts = []
        for acct in data.get("accounts", []):
            accounts.append({
                "account_id": acct.get("account_id"),
                "name": acct.get("name"),
                "official_name": acct.get("official_name"),
                "type": acct.get("type"),
                "subtype": acct.get("subtype"),
                "current_balance": acct.get("balances", {}).get("current"),
                "currency": acct.get("balances", {}).get("iso_currency_code"),
            })
        return accounts

    async def get_spending_summary(self) -> dict:
        """
        Return aggregated spending by category and weekly/monthly totals.
        Sensitive categories (emotional_capability) are excluded from the summary.
        """
        transactions = await self.get_transactions(days=30)

        by_category: dict[str, float] = defaultdict(float)
        weekly_total = 0.0
        monthly_total = 0.0
        cutoff_weekly = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()

        for txn in transactions:
            amount = txn.get("amount") or 0
            if amount <= 0:
                continue  # skip credits/refunds

            signal = txn.get("capability_signal")
            # Exclude sensitive signals from summary
            if signal in SENSITIVE_SIGNALS:
                continue

            cats = txn.get("categories", [])
            category_label = cats[0] if cats else "Other"
            by_category[category_label] += amount
            monthly_total += amount
            if txn.get("date", "") >= cutoff_weekly:
                weekly_total += amount

        return {
            "monthly_total": round(monthly_total, 2),
            "weekly_total": round(weekly_total, 2),
            "by_category": {k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
            "transaction_count": len(transactions),
            "period_days": 30,
        }

    async def disconnect(self) -> None:
        """Remove the Plaid connection and access token. Cannot be undone."""
        try:
            # Revoke the access token at Plaid
            access_token = await self._get_access_token()
            await self._post("/item/remove", {"access_token": access_token})
        except Exception as exc:
            logger.warning("Could not revoke Plaid item for %s: %s", self.user_id, exc)

        try:
            import database as db_mod
            db_mod.get_db().table("financial_accounts").delete().eq("user_id", self.user_id).execute()
        except Exception as exc:
            logger.error("Could not remove financial_accounts row for %s: %s", self.user_id, exc)
            raise

    # ── Capability signal helpers ─────────────────────────────────────────────

    def _map_to_signal(self, categories: list[str]) -> Optional[str]:
        """Map a list of Plaid category strings to a capability signal key."""
        for cat in categories:
            for keyword, signal in CATEGORY_SIGNAL_MAP.items():
                if keyword in cat:
                    return signal
        return None

    def extract_capability_signals(self, transactions: list[dict]) -> list[dict]:
        """
        Distill transactions into capability signals.
        Sensitive signals (emotional_capability) are included for internal
        rule evaluation but NEVER returned via the public API or stored in
        the people graph.
        """
        signal_counts: dict[str, int] = defaultdict(int)
        for txn in transactions:
            signal = txn.get("capability_signal")
            if signal:
                signal_counts[signal] += 1

        signals = []
        for signal_type, count in signal_counts.items():
            signals.append({
                "type": signal_type,
                "count": count,
                "sensitive": signal_type in SENSITIVE_SIGNALS,
            })
        return signals
