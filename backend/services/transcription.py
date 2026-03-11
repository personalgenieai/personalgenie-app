"""
services/transcription.py — OpenAI Whisper voice note transcription.
Accepts audio bytes, returns a text transcript.
"""
import logging
import tempfile
import os
from openai import OpenAI
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client = OpenAI(api_key=settings.openai_api_key)


def transcribe_audio(audio_bytes: bytes, filename: str = "voice_note.m4a") -> str:
    """
    Send audio to OpenAI Whisper and get back a text transcript.

    Saves audio to a temp file (Whisper requires a file, not raw bytes),
    sends it, then cleans up the temp file.

    Returns the transcript as a string, or empty string on failure.
    """
    # Write to temp file — Whisper API needs a file object
    suffix = os.path.splitext(filename)[1] or ".m4a"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as audio_file:
            response = _client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="en",
            )
        transcript = response.text
        logger.info(f"Transcribed {len(audio_bytes)} bytes → {len(transcript)} chars")
        return transcript

    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return ""

    finally:
        # Always clean up the temp file
        os.unlink(tmp_path)
