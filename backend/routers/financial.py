"""
routers/financial.py — Plaid financial data endpoints.

POST /financial/link-token     — create Plaid Link token for iOS
POST /financial/connect        — exchange public token, save connection
GET  /financial/status         — is Plaid connected, last synced
GET  /financial/summary        — spending summary (authenticated)
POST /financial/disconnect     — remove Plaid connection
POST /financial/sync           — trigger manual sync of recent transactions

Privacy: raw transactions are never returned. Only aggregated summaries.
Sensitive signals (mental health, therapy) are never surfaced via this API.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.plaid_client import PlaidClient
from routers.auth import verify_app_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/financial", tags=["financial"])


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

class ConnectRequest(BaseModel):
    public_token: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/link-token")
async def create_link_token(request: Request):
    """
    Create a Plaid Link token for the iOS app.
    The iOS app opens Plaid Link with this token; after success it sends
    the public_token back to POST /financial/connect.
    """
    user_id = _get_user_id(request)
    client = PlaidClient(user_id)
    try:
        link_token = await client.create_link_token()
    except Exception as exc:
        logger.error("Plaid create_link_token failed for %s: %s", user_id, exc)
        raise HTTPException(status_code=502, detail="Could not create Plaid Link token")
    return {"link_token": link_token}


@router.post("/connect")
async def connect_financial(request: Request, body: ConnectRequest):
    """
    Exchange the public_token returned by Plaid Link for a permanent
    access token and save the connection.
    """
    user_id = _get_user_id(request)
    client = PlaidClient(user_id)
    try:
        await client.exchange_public_token(body.public_token)
    except Exception as exc:
        logger.error("Plaid exchange_public_token failed for %s: %s", user_id, exc)
        raise HTTPException(status_code=502, detail="Could not connect financial account")
    return {"status": "connected"}


@router.get("/status")
async def financial_status(request: Request):
    """Return whether Plaid is connected and when it was last synced."""
    user_id = _get_user_id(request)
    try:
        import database as db_mod
        db = db_mod.get_db()
        row = (
            db.table("financial_accounts")
            .select("institution_name, last_synced, item_id")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if row.data:
            return {
                "connected": True,
                "institution_name": row.data.get("institution_name"),
                "last_synced": row.data.get("last_synced"),
            }
    except Exception:
        pass
    return {"connected": False}


@router.get("/summary")
async def financial_summary(request: Request):
    """
    Return aggregated spending summary for the last 30 days.
    Sensitive categories are excluded. No raw transactions returned.
    """
    user_id = _get_user_id(request)
    client = PlaidClient(user_id)
    try:
        summary = await client.get_spending_summary()
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Plaid get_spending_summary failed for %s: %s", user_id, exc)
        raise HTTPException(status_code=502, detail="Could not fetch spending summary")
    return summary


@router.post("/disconnect")
async def financial_disconnect(request: Request):
    """Remove the Plaid connection. Access token is deleted from DB and revoked at Plaid."""
    user_id = _get_user_id(request)
    client = PlaidClient(user_id)
    try:
        await client.disconnect()
    except Exception as exc:
        logger.warning("Plaid disconnect partial failure for %s: %s", user_id, exc)
        # Don't raise — best-effort disconnect
    return {"status": "disconnected"}


@router.post("/sync")
async def financial_sync(request: Request):
    """
    Trigger a manual sync. Fetches latest transactions and updates capability signals.
    Returns a summary of what changed.
    """
    user_id = _get_user_id(request)
    client = PlaidClient(user_id)
    try:
        transactions = await client.get_transactions(days=30)
        signals = client.extract_capability_signals(transactions)
        # Filter out sensitive signals before returning
        public_signals = [s for s in signals if not s.get("sensitive")]
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Plaid sync failed for %s: %s", user_id, exc)
        raise HTTPException(status_code=502, detail="Sync failed")

    return {
        "status": "synced",
        "transaction_count": len(transactions),
        "capability_signals": public_signals,
    }
