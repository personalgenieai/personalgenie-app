"""
routers/voice.py — Voice note upload and transcription.

POST /voice/upload — accepts audio from the iOS app,
transcribes it with Whisper, extracts relationship intelligence with Claude,
updates Supabase, and sends a WhatsApp confirmation.
"""
import logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
import database as db
from services.transcription import transcribe_audio
from services.intelligence import process_voice_note
from services.whatsapp import send_voice_note_confirmation
from config import get_settings
from policy_engine.guard import check, PolicyViolationError

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/upload")
async def upload_voice_note(
    audio: UploadFile = File(...),
    user_id: str = Form(...),
    person_id: str = Form(...),
):
    """
    Accept a voice note recording from the iOS app.

    Flow:
    1. Read audio bytes
    2. Whisper transcription
    3. Claude extracts relationship intelligence
    4. Update person record in Supabase
    5. Send WhatsApp confirmation to the user

    Plain English: Leo holds the mic button, talks about a call with his brother,
    releases — and Genie remembers everything he said.
    """
    # Get user and person for context
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    person = db.get_person_by_id(person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # Policy check: consent required before processing any voice note
    try:
        check("process_voice_note", {
            "user_id": user_id,
            "data_type": "voice_note_transcript",
            "consent_status": user.get("whatsapp_consented", False),
            "whatsapp_consented": user.get("whatsapp_consented", False),
            "sender_consented": True,
        })
    except PolicyViolationError as e:
        raise HTTPException(status_code=403, detail=str(e))

    person_name = person.get("name", "them")
    user_phone = user.get("phone", "")

    # Read the audio file
    audio_bytes = await audio.read()
    if len(audio_bytes) < 1000:
        raise HTTPException(status_code=400, detail="Audio file too small")

    logger.info(f"Processing voice note: {len(audio_bytes)} bytes about {person_name}")

    # Step 1: Transcribe with Whisper
    transcript = transcribe_audio(audio_bytes, filename=audio.filename or "voice_note.m4a")
    if not transcript:
        raise HTTPException(status_code=500, detail="Transcription failed")

    # Step 2: Extract relationship intelligence with Claude
    extracted = process_voice_note(
        user_id=user_id,
        person_name=person_name,
        transcript=transcript,
    )

    # Step 3: Update person record with new memories and emotions
    existing_memories = person.get("memories", [])
    new_memories = [
        {"description": m, "source": "voice_note"}
        for m in extracted.get("memories", [])
    ]

    db.upsert_person(user_id, {
        "name": person_name,
        "memories": existing_memories + new_memories,
    })

    # Step 4: Save the full call note
    db.save_call_note(
        user_id=user_id,
        person_id=person_id,
        audio_url="",  # Phase 2: upload to Supabase Storage
        transcript=transcript,
        extracted=extracted,
    )

    # Step 5: Create a moment if follow-up was flagged
    followup = extracted.get("suggested_followup", {})
    if followup.get("suggestion"):
        db.create_moment(
            user_id=user_id,
            person_id=person_id,
            suggestion=followup["suggestion"],
            triggered_by="voice_note",
        )

    # Step 6: Send WhatsApp confirmation
    if user_phone:
        send_voice_note_confirmation(user_phone, person_name)

    return {
        "status": "processed",
        "transcript": transcript,
        "memories_extracted": len(new_memories),
        "followup_created": bool(followup.get("suggestion")),
    }
