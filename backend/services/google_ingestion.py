"""
services/google_ingestion.py — Google Photos, Gmail, and Contacts ingestion.

Runs in parallel background threads after Google OAuth completes.
Pulls the user's data and feeds it to Claude for People Graph synthesis.

Plain English: after someone connects Google, this code quietly reads
their photos, emails and contacts to understand who matters in their life.
"""
import asyncio
import logging
from typing import Optional, Tuple
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def refresh_google_tokens(user_id: str) -> Optional[tuple]:
    """
    Use the stored refresh token to get a fresh access token.
    Google access tokens expire after 1 hour — this keeps them valid indefinitely.

    Returns (new_access_token, new_refresh_token) or None if refresh fails.
    Call this before any Google API operation rather than assuming the stored token works.
    """
    import requests as _requests
    import database as db

    user = db.get_user_by_id(user_id)
    if not user:
        return None

    refresh_token = user.get("google_refresh_token")
    if not refresh_token:
        logger.warning(f"No refresh token for user {user_id} — user must re-authenticate")
        return None

    try:
        resp = _requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        data = resp.json()
        new_access_token = data["access_token"]
        # Google may issue a new refresh token — if so, save it
        new_refresh_token = data.get("refresh_token", refresh_token)

        db.get_db().table("users").update({
            "google_access_token": new_access_token,
            "google_refresh_token": new_refresh_token,
        }).eq("id", user_id).execute()

        logger.info(f"Google token refreshed for user {user_id}")
        return new_access_token, new_refresh_token

    except Exception as e:
        logger.error(f"Google token refresh failed for user {user_id}: {e}")
        return None


def get_valid_google_tokens(user_id: str) -> Optional[tuple]:
    """
    Return a valid (access_token, refresh_token) pair for a user.
    Refreshes automatically if the stored token is expired or about to expire.

    Returns None if the user has no Google connection or refresh fails.
    """
    import database as db
    from datetime import datetime, timezone

    user = db.get_user_by_id(user_id)
    if not user:
        return None

    access_token = user.get("google_access_token")
    refresh_token = user.get("google_refresh_token")

    if not access_token or not refresh_token:
        return None

    # Check expiry — refresh proactively if within 5 minutes of expiring
    expiry = user.get("google_token_expiry")
    if expiry:
        try:
            expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            from datetime import timedelta
            if datetime.now(timezone.utc) >= expiry_dt - timedelta(minutes=5):
                result = refresh_google_tokens(user_id)
                return result  # None if refresh failed
        except Exception:
            pass  # If we can't parse expiry, try the stored token first

    return access_token, refresh_token


def _get_credentials(access_token: str, refresh_token: str) -> Credentials:
    """Build a Google credentials object from stored OAuth tokens."""
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=[
            "https://www.googleapis.com/auth/photoslibrary.readonly",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/contacts.readonly",
        ]
    )


# ── Google Photos ─────────────────────────────────────────────────────────────

def fetch_photos_data(access_token: str, refresh_token: str) -> dict:
    """
    Fetch the top 15 people albums from Google Photos, ranked by photo count.
    For each person, get their 5 most recent and 5 oldest photos with metadata.
    Also fetch Google Photos Memories and Highlights.

    Returns a dict with people albums and memories.
    """
    import requests

    headers = {"Authorization": f"Bearer {access_token}"}
    base_url = "https://photoslibrary.googleapis.com/v1"

    result = {"people_albums": [], "memories": []}

    try:
        # List all albums
        albums_resp = requests.get(f"{base_url}/albums?pageSize=50", headers=headers)
        if albums_resp.status_code != 200:
            logger.warning(f"Photos API error: {albums_resp.status_code} — {albums_resp.text[:300]}")
            return result

        albums = albums_resp.json().get("albums", [])

        # Sort by photo count, take top 15
        albums_with_counts = [
            a for a in albums if a.get("mediaItemsCount", "0") != "0"
        ]
        albums_with_counts.sort(
            key=lambda a: int(a.get("mediaItemsCount", "0")), reverse=True
        )
        top_albums = albums_with_counts[:15]

        for album in top_albums:
            album_id = album["id"]
            album_title = album.get("title", "Unknown")
            photo_count = int(album.get("mediaItemsCount", "0"))

            # Fetch media items for this album
            media_resp = requests.post(
                f"{base_url}/mediaItems:search",
                headers=headers,
                json={"albumId": album_id, "pageSize": 100}
            )

            if media_resp.status_code != 200:
                continue

            items = media_resp.json().get("mediaItems", [])

            # Sort by creation time to get oldest and newest
            items_with_dates = [
                i for i in items if i.get("mediaMetadata", {}).get("creationTime")
            ]
            items_with_dates.sort(
                key=lambda i: i["mediaMetadata"]["creationTime"]
            )

            oldest_5 = items_with_dates[:5]
            newest_5 = items_with_dates[-5:]
            key_photos = oldest_5 + newest_5

            photos_data = []
            for photo in key_photos:
                metadata = photo.get("mediaMetadata", {})
                photos_data.append({
                    "date": metadata.get("creationTime", ""),
                    "filename": photo.get("filename", ""),
                    "description": photo.get("description", ""),
                    "location": metadata.get("photo", {}).get("cameraMake", ""),
                })

            result["people_albums"].append({
                "person_name": album_title,
                "photo_count": photo_count,
                "oldest_photo_date": items_with_dates[0]["mediaMetadata"]["creationTime"] if items_with_dates else "",
                "newest_photo_date": items_with_dates[-1]["mediaMetadata"]["creationTime"] if items_with_dates else "",
                "key_photos": photos_data,
            })

    except Exception as e:
        logger.error(f"Error fetching Google Photos: {e}")

    return result


# ── Gmail ─────────────────────────────────────────────────────────────────────

def fetch_gmail_data(access_token: str, refresh_token: str) -> dict:
    """
    Find the top 20 most frequent email contacts.
    For each one extract: subject line patterns, recurring topics,
    thread depth (how deep conversations go), travel/calendar mentions.

    Returns a list of contact summaries with relationship signals.
    """
    creds = _get_credentials(access_token, refresh_token)

    result = {"frequent_contacts": []}

    try:
        service = build("gmail", "v1", credentials=creds)

        # Get the last 500 sent emails to find who we communicate with most
        sent = service.users().messages().list(
            userId="me",
            labelIds=["SENT"],
            maxResults=500
        ).execute()

        messages = sent.get("messages", [])

        # Count emails per recipient
        contact_counts: dict = {}
        contact_subjects: dict = {}

        for msg_ref in messages[:500]:  # process up to 500 for better coverage
            try:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["To", "Subject"]
                ).execute()

                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                to = headers.get("To", "")
                subject = headers.get("Subject", "")

                if to and "@" in to:
                    # Normalize the email address
                    email = to.split("<")[-1].replace(">", "").strip()
                    contact_counts[email] = contact_counts.get(email, 0) + 1
                    if email not in contact_subjects:
                        contact_subjects[email] = []
                    if subject:
                        contact_subjects[email].append(subject)

            except Exception:
                continue

        # Take top 50 contacts by email count
        top_contacts = sorted(contact_counts.items(), key=lambda x: x[1], reverse=True)[:50]

        for email, count in top_contacts:
            subjects = contact_subjects.get(email, [])[:10]  # last 10 subjects
            result["frequent_contacts"].append({
                "email": email,
                "email_count": count,
                "recent_subjects": subjects,
                "has_travel": any(
                    word in " ".join(subjects).lower()
                    for word in ["flight", "hotel", "trip", "travel", "booking", "reservation"]
                ),
                "has_calendar": any(
                    word in " ".join(subjects).lower()
                    for word in ["invite", "meeting", "calendar", "schedule"]
                ),
            })

    except Exception as e:
        logger.error(f"Error fetching Gmail: {e}")

    return result


# ── Google Contacts ───────────────────────────────────────────────────────────

def fetch_contacts_data(access_token: str, refresh_token: str) -> dict:
    """
    Pull all Google Contacts with birthdays, phone numbers, and emails.
    Paginates through all pages (Google caps each page at 100 by default).
    Cross-reference later with Photos people albums to enrich records.
    """
    creds = _get_credentials(access_token, refresh_token)

    result = {"contacts": []}

    try:
        service = build("people", "v1", credentials=creds)

        # Paginate through ALL contacts — Google returns max ~100 per page
        # even when pageSize=1000, so we must follow nextPageToken
        all_persons = []
        page_token = None
        while True:
            kwargs = dict(
                resourceName="people/me",
                pageSize=1000,
                personFields="names,emailAddresses,phoneNumbers,birthdays,organizations"
            )
            if page_token:
                kwargs["pageToken"] = page_token

            connections = service.people().connections().list(**kwargs).execute()
            all_persons.extend(connections.get("connections", []))

            page_token = connections.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"Fetched {len(all_persons)} total contacts across all pages")

        for person in all_persons:
            names = person.get("names", [])
            emails = [e["value"] for e in person.get("emailAddresses", [])]
            phones = [p["value"] for p in person.get("phoneNumbers", [])]

            if names:
                name = names[0].get("displayName", "")
            elif phones:
                name = phones[0]  # no display name — phone as placeholder
            elif emails:
                name = emails[0]
            else:
                continue

            if not name:
                continue

            # Extract birthday if available
            birthday = None
            for bd in person.get("birthdays", []):
                date = bd.get("date", {})
                if date.get("month") and date.get("day"):
                    birthday = f"{date.get('month', '')}/{date.get('day', '')}"
                    if date.get("year"):
                        birthday = f"{date['year']}-{birthday}"

            result["contacts"].append({
                "name": name,
                "emails": emails,
                "phones": phones,
                "birthday": birthday,
            })

    except Exception as e:
        logger.error(f"Error fetching Contacts: {e}")

    return result


# ── Full ingestion pipeline ───────────────────────────────────────────────────

async def run_full_ingestion(user_id: str, access_token: str, refresh_token: str) -> dict:
    """
    Run Photos + Gmail + Contacts ingestion in parallel.
    Broadcasts real-time progress to the iOS app via WebSocket if the user
    has an active onboarding session registered in the ingestion bus.

    Returns all three datasets merged — ready to send to Claude.
    """
    from services.ingestion_bus import get_session, broadcast_async

    session_id = get_session(user_id)
    logger.info(f"Starting Google ingestion for user {user_id} (session={session_id or 'none'})")

    async def _emit(progress: int, message: str, source: str = "google",
                    stage: str = "reading", insight: str | None = None,
                    people_found: int = 0) -> None:
        if session_id:
            await broadcast_async(
                session_id, source, stage, progress, message,
                insight=insight, people_found=people_found, user_id=user_id,
            )

    await _emit(3, "Opening your Google account…", stage="starting")

    loop = asyncio.get_event_loop()

    # ── Contacts (fastest, broadcast first) ────────────────────────────────────
    await _emit(8, "Reading your contacts…", source="contacts")
    contacts_future = loop.run_in_executor(None, fetch_contacts_data, access_token, refresh_token)

    # ── Gmail (parallel with contacts) ─────────────────────────────────────────
    await _emit(15, "Scanning your sent emails to see who you talk to most…", source="gmail")
    gmail_future = loop.run_in_executor(None, fetch_gmail_data, access_token, refresh_token)

    # ── Photos ──────────────────────────────────────────────────────────────────
    await _emit(22, "Looking through your photo albums…", source="photos")
    photos_future = loop.run_in_executor(None, fetch_photos_data, access_token, refresh_token)

    # Wait for contacts first — smallest dataset
    contacts_data = await contacts_future
    n_contacts = len(contacts_data.get("contacts", []))
    await _emit(
        35,
        f"Found {n_contacts} people in your contacts.",
        source="contacts",
        stage="reading",
        insight=f"{n_contacts} contacts imported" if n_contacts else None,
        people_found=n_contacts,
    )

    # Wait for Gmail
    gmail_data = await gmail_future
    n_email = len(gmail_data.get("frequent_contacts", []))
    await _emit(
        50,
        f"Read {n_email} email relationships.",
        source="gmail",
        stage="reading",
        insight=f"You email {n_email} people regularly" if n_email else None,
        people_found=n_contacts,
    )

    # Wait for Photos
    photos_data = await photos_future
    n_albums = len(photos_data.get("people_albums", []))
    await _emit(
        65,
        f"Found {n_albums} photo album{'' if n_albums == 1 else 's'} with people you care about.",
        source="photos",
        stage="reading",
        insight=f"{n_albums} photo albums found" if n_albums else None,
        people_found=n_contacts,
    )

    await _emit(
        72,
        "Putting the picture together…",
        source="google",
        stage="analyzing",
        people_found=n_contacts,
    )

    logger.info(
        f"Google ingestion complete for user {user_id}: "
        f"{n_albums} photo albums, {n_email} email contacts, {n_contacts} contacts"
    )

    return {
        "user_id":  user_id,
        "photos":   photos_data,
        "gmail":    gmail_data,
        "contacts": contacts_data,
    }
