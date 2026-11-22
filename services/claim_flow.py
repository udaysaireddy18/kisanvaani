"""Claim state machine and conversation flow for KisanVaani.

Handles inbound WhatsApp messages, updates claim state, asks follow-up
questions, stores messages/media, and transitions claims through:
NEW -> COLLECTING -> READY -> PDF_GENERATED.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from db.models import Claim, ClaimStatus, Media, Message, MessageDirection
from db.session import session_scope
from services.extractor import extract_fields, merge_extraction
from services.stt import STTError, transcribe_audio
from services.whatsapp import WhatsAppAPIError, download_media, send_text

logger = logging.getLogger(__name__)
REQUIRED_FIELDS = ["crop", "damage", "village", "date"]
MAX_FOLLOWUPS = 2


def process_incoming_message(message: dict[str, Any], phone: str, raw_payload: dict[str, Any]) -> None:
    """Route an inbound WhatsApp message through the claim flow."""
    msg_id = str(message.get("id") or "").strip() or None
    msg_type = str(message.get("type") or "unknown").strip().lower()
    logger.info("Processing inbound message phone=%s type=%s msg_id=%s", phone, msg_type, msg_id)

    try:
        if msg_type == "text":
            _handle_text(message, phone, msg_id, raw_payload)
        elif msg_type == "audio":
            _handle_audio(message, phone, msg_id, raw_payload)
        elif msg_type == "image":
            _handle_image(message, phone, msg_id, raw_payload)
        else:
            _handle_unsupported(phone, msg_id, msg_type, raw_payload)
    except Exception:
        logger.exception("Claim flow failed phone=%s msg_id=%s type=%s", phone, msg_id, msg_type)
        _safe_send(phone, "Maaf kijiye, abhi aapka sandesh process nahi ho saka. Kripya thodi der baad dobara bhejein.")


def _handle_text(message: dict[str, Any], phone: str, msg_id: str | None, raw_payload: dict[str, Any]) -> None:
    """Handle inbound text messages."""
    text = ((message.get("text") or {}).get("body") or "").strip()
    extraction = extract_fields(text)
    with session_scope() as session:
        claim = _get_or_create_open_claim(session, phone)
        logger.info("Incoming message logged phone=%s type=text claim_id=%s msg_id=%s", phone, claim.id, msg_id)
        _save_message(session, claim, phone, msg_id, "text", text, None, raw_payload)
        _apply_extraction(claim, extraction)
        reply = _next_reply(session, claim)
        session.add_all(_outbound_messages(claim, phone, reply))
        claim_id = claim.id
    _send_replies(phone, reply)
    logger.info("Handled text phone=%s claim_id=%s", phone, claim_id)


def _handle_audio(message: dict[str, Any], phone: str, msg_id: str | None, raw_payload: dict[str, Any]) -> None:
    """Handle inbound audio/voice messages: download, transcribe, extract."""
    audio_info = message.get("audio") or {}
    media_id = str(audio_info.get("id") or "").strip()
    if not media_id:
        _safe_send(phone, "Audio mila, lekin media ID nahi mila. Kripya dobara bhejein.")
        return

    try:
        downloaded = download_media(media_id, media_type="audio")
    except WhatsAppAPIError:
        _safe_send(phone, "Audio download nahi ho saka. Kripya dobara voice note bhejein.")
        return

    transcript = ""
    try:
        transcript = transcribe_audio(downloaded["file_path"])
    except STTError:
        logger.exception("STT failed phone=%s msg_id=%s", phone, msg_id)

    extraction = extract_fields(transcript) if transcript else _empty_extraction()
    with session_scope() as session:
        claim = _get_or_create_open_claim(session, phone)
        logger.info("Incoming message logged phone=%s type=audio claim_id=%s msg_id=%s", phone, claim.id, msg_id)
        _save_message(session, claim, phone, msg_id, "audio", media_id, transcript, raw_payload)
        session.add(Media(
            claim_id=claim.id, media_type="audio", whatsapp_media_id=media_id,
            file_path=downloaded["file_path"], mime_type=downloaded.get("mime_type"),
        ))
        if transcript:
            _apply_extraction(claim, extraction)
            reply = _next_reply(session, claim)
        else:
            reply = ["Mujhe aapka voice note samajh nahi aaya. Kripya dobara clearly boliye: fasal, nuksan, gaon, aur date."]
        session.add_all(_outbound_messages(claim, phone, reply))
        claim_id = claim.id
    _send_replies(phone, reply)
    logger.info("Handled audio phone=%s claim_id=%s transcript_len=%s", phone, claim_id, len(transcript))


def _handle_image(message: dict[str, Any], phone: str, msg_id: str | None, raw_payload: dict[str, Any]) -> None:
    """Handle inbound image messages: download, attach to claim, update state."""
    image_info = message.get("image") or {}
    media_id = str(image_info.get("id") or "").strip()
    caption = (image_info.get("caption") or "").strip()
    if not media_id:
        _safe_send(phone, "Photo mili, lekin media ID nahi mila. Kripya dobara bhejein.")
        return

    try:
        downloaded = download_media(media_id, media_type="image")
    except WhatsAppAPIError:
        _safe_send(phone, "Photo download nahi ho saka. Kripya dobara photo bhejein.")
        return

    extraction = extract_fields(caption) if caption else _empty_extraction()
    with session_scope() as session:
        claim = _get_or_create_open_claim(session, phone)
        logger.info("Incoming message logged phone=%s type=image claim_id=%s msg_id=%s", phone, claim.id, msg_id)
        _save_message(session, claim, phone, msg_id, "image", caption or media_id, None, raw_payload)
        session.add(Media(
            claim_id=claim.id, media_type="image", whatsapp_media_id=media_id,
            file_path=downloaded["file_path"], mime_type=downloaded.get("mime_type"),
        ))
        session.flush()  # Make the photo visible to _next_reply's photo count.
        if caption:
            _apply_extraction(claim, extraction)
        reply = _next_reply(session, claim)
        session.add_all(_outbound_messages(claim, phone, reply))
        claim_id = claim.id
    _send_replies(phone, reply)
    logger.info("Handled image phone=%s claim_id=%s", phone, claim_id)


def _handle_unsupported(phone: str, msg_id: str | None, msg_type: str, raw_payload: dict[str, Any]) -> None:
    """Handle unsupported message types politely."""
    with session_scope() as session:
        claim = _get_or_create_open_claim(session, phone)
        _save_message(session, claim, phone, msg_id, msg_type, None, None, raw_payload)
        reply = ["Kripya text, voice note, ya photo bhejein taaki hum aapka claim bana sakein."]
        session.add_all(_outbound_messages(claim, phone, reply))
    _send_replies(phone, reply)


def _get_or_create_open_claim(session: Any, phone: str) -> Claim:
    """Get latest open claim for phone, or create a new one."""
    claim = (
        session.query(Claim)
        .filter(Claim.farmer_phone == phone, Claim.status != ClaimStatus.PDF_GENERATED)
        .order_by(Claim.created_at.desc())
        .first()
    )
    if claim:
        return claim
    claim = Claim(farmer_phone=phone, status=ClaimStatus.NEW, missing_fields=list(REQUIRED_FIELDS))
    session.add(claim)
    session.flush()
    logger.info("Created claim claim_id=%s phone=%s", claim.id, phone)
    return claim


def _save_message(session: Any, claim: Claim, phone: str, msg_id: str | None,
                  msg_type: str, content: str | None, transcript: str | None, raw_payload: dict[str, Any]) -> None:
    """Persist an inbound message linked to a claim."""
    session.add(Message(
        claim_id=claim.id, whatsapp_message_id=msg_id, direction=MessageDirection.INBOUND,
        phone=phone, msg_type=msg_type, content=content, transcript=transcript,
        raw_payload=json.dumps(raw_payload, ensure_ascii=False),
    ))


def _apply_extraction(claim: Claim, extraction: dict[str, Any]) -> None:
    """Merge extraction into claim and update status/missing fields."""
    existing = {
        "crop": claim.crop or "", "damage": claim.damage_type or "",
        "village": claim.village or "", "date": claim.incident_date or "",
    }
    merged = merge_extraction(existing, extraction)
    claim.crop = merged["crop"] or None
    claim.damage_type = merged["damage"] or None
    claim.village = merged["village"] or None
    claim.incident_date = merged["date"] or None
    claim.missing_fields = merged["missing"]
    claim.confidence = float(merged["confidence"])
    if claim.status == ClaimStatus.NEW:
        claim.status = ClaimStatus.COLLECTING
    logger.info("Claim updated claim_id=%s missing=%s status=%s", claim.id, claim.missing_fields, claim.status.value)


def _next_reply(session: Any, claim: Claim) -> list[str]:
    """Decide next bot replies based on claim state and missing info."""
    missing = list(claim.missing_fields or [])
    photos = _count_photos(session, claim.id)

    if missing and claim.followup_count < MAX_FOLLOWUPS:
        claim.followup_count += 1
        return [_question_for(missing[0])]

    if missing:
        return ["Kripya poori jankari bhejein: fasal, nuksan ka prakar, gaon, aur date (DD/MM/YYYY)."]

    if photos < 1:
        if claim.status != ClaimStatus.READY:
            claim.status = ClaimStatus.COLLECTING
        return ["Dhanyavaad. Kripya 1-3 nuksan ki photo bhejein."]

    if claim.status != ClaimStatus.PDF_GENERATED:
        claim.status = ClaimStatus.READY
    return [f"Aapka claim tayyar hai. Claim ID: {claim.id}. Operator dashboard se PDF generate kiya jayega."]


def _question_for(field: str) -> str:
    """Return a clarifying question for a missing field."""
    questions = {
        "crop": "Kaunsi fasal kharab hui hai? (jaise: ganna, gehu, dhan)",
        "damage": "Fasal ko kya nuksan hua? (jaise: barish, sukhna, keede, aag)",
        "village": "Aapka gaon/village ka naam kya hai?",
        "date": "Fasal kab kharab hui? Date bataiye (DD/MM/YYYY).",
    }
    return questions.get(field, "Kripya poori jankari bhejein.")


def _count_photos(session: Any, claim_id: str) -> int:
    """Count image media attached to a claim."""
    return session.query(Media).filter(Media.claim_id == claim_id, Media.media_type == "image").count()


def _outbound_messages(claim: Claim, phone: str, replies: list[str]) -> list[Message]:
    """Create outbound message records for bot replies."""
    return [Message(claim_id=claim.id, direction=MessageDirection.OUTBOUND, phone=phone,
                    msg_type="text", content=text) for text in replies]


def _send_replies(phone: str, replies: list[str]) -> None:
    """Send reply messages over WhatsApp, logging failures."""
    for text in replies:
        try:
            send_text(phone, text)
        except Exception:
            logger.exception("Failed sending reply phone=%s", phone)


def _safe_send(phone: str, text: str) -> None:
    """Best-effort WhatsApp send for error cases."""
    try:
        send_text(phone, text)
    except Exception:
        logger.exception("Safe send failed phone=%s", phone)


def _empty_extraction() -> dict[str, Any]:
    """Return an empty extraction result."""
    return {"crop": "", "damage": "", "village": "", "date": "", "missing": list(REQUIRED_FIELDS), "confidence": 0.0}
