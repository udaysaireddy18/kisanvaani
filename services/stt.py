"""Speech-to-text service for KisanVaani.

Transcribes farmer voice notes to text using OpenAI Whisper API.
Optional fallback to Google Speech-to-Text when configured.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config import OPENAI_API_KEY, STT_PROVIDER

logger = logging.getLogger(__name__)


class STTError(RuntimeError):
    """Raised when speech-to-text transcription fails."""


def transcribe_audio(audio_path: str) -> str:
    """Transcribe an audio file to text using the configured STT provider."""
    path = Path(audio_path)
    if not path.exists() or not path.is_file():
        logger.error("STT audio file missing: %s", audio_path)
        raise STTError(f"Audio file not found: {audio_path}")

    provider = (STT_PROVIDER or "openai").lower().strip()
    logger.info("Transcribing audio provider=%s path=%s", provider, path)

    try:
        if provider == "google":
            return _transcribe_google(path)
        return _transcribe_openai(path)
    except STTError:
        raise
    except Exception as exc:
        logger.exception("Unexpected STT failure provider=%s path=%s", provider, path)
        raise STTError("Speech-to-text failed") from exc


def _transcribe_openai(path: Path) -> str:
    """Transcribe audio via OpenAI Whisper API."""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY missing for Whisper transcription")
        raise STTError("OPENAI_API_KEY is not configured")

    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        with path.open("rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        transcript = (getattr(response, "text", "") or "").strip()
        logger.info("Whisper transcript length=%s path=%s", len(transcript), path)
        return transcript
    except Exception as exc:
        logger.exception("OpenAI Whisper transcription failed for %s", path)
        raise STTError("OpenAI Whisper transcription failed") from exc


def _transcribe_google(path: Path) -> str:
    """Transcribe audio via Google Speech-to-Text as an optional fallback."""
    try:
        from google.cloud import speech  # type: ignore
    except Exception as exc:
        logger.exception("Google STT dependency unavailable")
        raise STTError("google-cloud-speech is not installed/configured") from exc

    try:
        client = speech.SpeechClient()
        content = path.read_bytes()
        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(language_code="hi-IN", enable_automatic_punctuation=True)
        response = client.recognize(config=config, audio=audio)
        parts = []
        for result in response.results:
            if result.alternatives:
                parts.append(result.alternatives[0].transcript)
        transcript = " ".join(p.strip() for p in parts if p and p.strip()).strip()
        logger.info("Google STT transcript length=%s path=%s", len(transcript), path)
        return transcript
    except Exception as exc:
        logger.exception("Google STT transcription failed for %s", path)
        raise STTError("Google STT transcription failed") from exc
