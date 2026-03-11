"""
routers/people.py — People Graph API for the iOS app.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Header
from typing import Optional
import database as db
from policy_engine.guard import check, PolicyViolationError

router = APIRouter(prefix="/people", tags=["people"])


@router.get("/{user_id}")
async def get_people(user_id: str, x_user_id: Optional[str] = Header(None)):
    """Get all people in a user's relationship graph, ordered by closeness."""
    user = db.get_user_by_id(user_id)
    try:
        check("access_user_data", {
            "auth_token_user_id": x_user_id or user_id,
            "requesting_user_id": user_id,
            "whatsapp_consented": bool(user and user.get("whatsapp_consented")),
            "consent_status": bool(user),
        })
    except PolicyViolationError as e:
        raise HTTPException(status_code=403, detail=str(e))
    people = db.get_people_for_user(user_id)
    return {"people": people}


@router.get("/{user_id}/moments")
async def get_moments(user_id: str, x_user_id: Optional[str] = Header(None)):
    """Get all moments for a user, ordered by urgency and recency."""
    user = db.get_user_by_id(user_id)
    try:
        check("access_user_data", {
            "auth_token_user_id": x_user_id or user_id,
            "requesting_user_id": user_id,
            "whatsapp_consented": bool(user and user.get("whatsapp_consented")),
            "consent_status": bool(user),
        })
    except PolicyViolationError as e:
        raise HTTPException(status_code=403, detail=str(e))
    result = db.get_db().table("moments").select("*, people(name, photo_url)") \
        .eq("owner_user_id", user_id) \
        .not_.eq("status", "dismissed") \
        .order("created_at", desc=True) \
        .limit(50) \
        .execute()
    return {"moments": result.data}


@router.get("/{user_id}/{person_id}")
async def get_person(user_id: str, person_id: str, x_user_id: Optional[str] = Header(None)):
    """Get a single person's full profile."""
    person = db.get_person_by_id(person_id)
    if not person or person.get("owner_user_id") != user_id:
        raise HTTPException(status_code=404, detail="Person not found")
    user = db.get_user_by_id(user_id)
    try:
        check("access_user_data", {
            "auth_token_user_id": x_user_id or user_id,
            "requesting_user_id": user_id,
            "whatsapp_consented": bool(user and user.get("whatsapp_consented")),
            "consent_status": bool(user),
        })
    except PolicyViolationError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return person


@router.patch("/{user_id}/{person_id}")
async def update_person(user_id: str, person_id: str, updates: dict,
                        x_user_id: Optional[str] = Header(None)):
    """Update a person's record — e.g. confirm their relationship type from the iOS app."""
    person = db.get_person_by_id(person_id)
    if not person or person.get("owner_user_id") != user_id:
        raise HTTPException(status_code=404, detail="Person not found")
    user = db.get_user_by_id(user_id)
    try:
        check("access_user_data", {
            "auth_token_user_id": x_user_id or user_id,
            "requesting_user_id": user_id,
            "whatsapp_consented": bool(user and user.get("whatsapp_consented")),
            "consent_status": bool(user),
        })
    except PolicyViolationError as e:
        raise HTTPException(status_code=403, detail=str(e))
    db.get_db().table("people").update(updates).eq("id", person_id).execute()
    return {"status": "updated"}


@router.post("/{user_id}/rebuild")
async def rebuild_graph(user_id: str, background_tasks: BackgroundTasks):
    """Re-run the People Graph build using stored Google tokens. Clears existing graph first."""
    user = db.get_db().table("users").select("*").eq("id", user_id).execute()
    if not user.data:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user.data[0]
    access_token = user_data.get("google_access_token")
    refresh_token = user_data.get("google_refresh_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No Google tokens — user must re-authenticate")

    background_tasks.add_task(_do_rebuild, user_id, access_token, refresh_token)
    return {"status": "rebuilding", "user_id": user_id}


async def _do_rebuild(user_id: str, access_token: str, refresh_token: str):
    import logging
    from services.google_ingestion import run_full_ingestion, get_valid_google_tokens
    from services.intelligence import build_people_graph
    from services.life_events import extract_from_contacts, extract_life_events_for_user
    logger = logging.getLogger(__name__)
    try:
        # Always refresh tokens before a rebuild — stored token may be stale
        tokens = get_valid_google_tokens(user_id)
        if tokens:
            access_token, refresh_token = tokens

        # Clear moments first (FK constraint), then people, then life events
        db.get_db().table("moments").delete().eq("owner_user_id", user_id).execute()
        db.get_db().table("life_events").delete().eq("owner_user_id", user_id).execute()
        db.get_db().table("people").delete().eq("owner_user_id", user_id).execute()
        logger.info(f"Cleared graph for user {user_id}, rebuilding...")

        ingestion_data = await run_full_ingestion(user_id, access_token, refresh_token)
        people = build_people_graph(user_id, ingestion_data)

        # Re-extract life events after rebuild
        contacts = ingestion_data.get("contacts", {}).get("contacts", [])
        extract_from_contacts(user_id, contacts)
        extract_life_events_for_user(user_id)

        logger.info(f"Rebuilt graph: {len(people)} people for user {user_id}")
    except Exception as e:
        logger.error(f"Rebuild failed for user {user_id}: {e}")


@router.get("/{user_id}/moments")
async def get_moments(user_id: str, x_user_id: str | None = None):
    """Get pending moments for the iOS app home screen."""
    moments = db.get_moments_for_user(user_id)
    return {"moments": moments[:5]}  # top 5 for the app
