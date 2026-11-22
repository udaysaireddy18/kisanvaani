"""Web API helpers for the public/demo web interface.

Reuses existing claim extraction, claim flow state machine, and PDF services.
This keeps the web demo behavior aligned with the future WhatsApp bot flow.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from config import MEDIA_DIR
from db.models import Claim, ClaimStatus, Media, Message, MessageDirection
from db.session import session_scope
from services.claim_flow import _apply_extraction, _next_reply, _outbound_messages
from services.extractor import extract_fields

logger = logging.getLogger(__name__)
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def process_web_text(phone: str, text: str, claim_id: str | None = None) -> dict[str, Any]:
    """Process a web text message through the existing claim flow logic."""
    phone = (phone or "").strip()
    text = (text or "").strip()
    if not phone or not text:
        raise ValueError("phone and message are required")

    extraction = extract_fields(text)
    with session_scope() as session:
        claim = _get_open_claim(session, phone, claim_id)
        _save_web_message(session, claim, phone, "text", text, transcript=None)
        _apply_extraction(claim, extraction)
        replies = _next_reply(session, claim)
        session.add_all(_outbound_messages(claim, phone, replies))
        session.flush()
        return {"replies": replies, "claim": serialize_claim(session, claim)}


def process_web_photo(phone: str, photo: FileStorage, claim_id: str | None = None) -> dict[str, Any]:
    """Save an uploaded photo and attach it to a claim."""
    phone = (phone or "").strip()
    if not phone:
        raise ValueError("phone is required")
    if not photo or not photo.filename:
        raise ValueError("photo file is required")

    ext = Path(secure_filename(photo.filename)).suffix.lower() or ".jpg"
    if ext not in ALLOWED_IMAGE_EXT:
        raise ValueError("Only image files are allowed (.jpg, .png, .webp)")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"web_{uuid.uuid4().hex}{ext}"
    file_path = MEDIA_DIR / filename
    photo.save(file_path)
    logger.info("Saved web photo phone=%s path=%s", phone, file_path)

    with session_scope() as session:
        claim = _get_open_claim(session, phone, claim_id)
        _save_web_message(session, claim, phone, "image", filename, transcript=None)
        session.add(Media(
            claim_id=claim.id, media_type="image", whatsapp_media_id=None,
            file_path=str(file_path), mime_type=photo.mimetype or "image/jpeg",
        ))
        replies = _next_reply(session, claim)
        session.add_all(_outbound_messages(claim, phone, replies))
        session.flush()
        return {"replies": replies, "claim": serialize_claim(session, claim)}


def get_claim_detail(claim_id: str) -> dict[str, Any] | None:
    """Return a serialized claim by ID."""
    with session_scope() as session:
        claim = session.get(Claim, claim_id)
        return serialize_claim(session, claim) if claim else None


def list_claims(limit: int = 50) -> list[dict[str, Any]]:
    """List recent claims for the web operator view."""
    with session_scope() as session:
        claims = session.query(Claim).order_by(Claim.created_at.desc()).limit(limit).all()
        return [serialize_claim(session, c) for c in claims]


def mark_pdf_generated(claim_id: str, pdf_path: str) -> dict[str, Any] | None:
    """Persist generated PDF path and mark claim as PDF_GENERATED."""
    with session_scope() as session:
        claim = session.get(Claim, claim_id)
        if not claim:
            return None
        claim.pdf_path = pdf_path
        claim.status = ClaimStatus.PDF_GENERATED
        session.flush()
        return serialize_claim(session, claim)


def serialize_claim(session: Any, claim: Claim) -> dict[str, Any]:
    """Serialize a claim for JSON API responses."""
    photos = session.query(Media).filter(Media.claim_id == claim.id, Media.media_type == "image").count()
    return {
        "id": claim.id,
        "farmer_phone": claim.farmer_phone,
        "status": claim.status.value if hasattr(claim.status, "value") else str(claim.status),
        "crop": claim.crop,
        "damage_type": claim.damage_type,
        "village": claim.village,
        "incident_date": claim.incident_date,
        "confidence": claim.confidence,
        "missing_fields": claim.missing_fields or [],
        "followup_count": claim.followup_count,
        "photo_count": photos,
        "pdf_path": claim.pdf_path,
        "created_at": claim.created_at.isoformat() if claim.created_at else None,
        "updated_at": claim.updated_at.isoformat() if claim.updated_at else None,
    }


def _get_open_claim(session: Any, phone: str, claim_id: str | None) -> Claim:
    """Find selected/open claim for a phone, else create a new one."""
    if claim_id:
        claim = session.get(Claim, claim_id)
        if claim and claim.farmer_phone == phone and claim.status != ClaimStatus.PDF_GENERATED:
            return claim

    claim = (
        session.query(Claim)
        .filter(Claim.farmer_phone == phone, Claim.status != ClaimStatus.PDF_GENERATED)
        .order_by(Claim.created_at.desc())
        .first()
    )
    if claim:
        return claim

    claim = Claim(farmer_phone=phone, status=ClaimStatus.NEW, missing_fields=["crop", "damage", "village", "date"])
    session.add(claim)
    session.flush()
    logger.info("Created web claim claim_id=%s phone=%s", claim.id, phone)
    return claim


def _save_web_message(session: Any, claim: Claim, phone: str, msg_type: str,
                      content: str | None, transcript: str | None) -> None:
    """Persist a web-originated inbound message."""
    raw = json.dumps({"source": "web", "msg_type": msg_type, "content": content}, ensure_ascii=False)
    session.add(Message(
        claim_id=claim.id, whatsapp_message_id=None, direction=MessageDirection.INBOUND,
        phone=phone, msg_type=msg_type, content=content, transcript=transcript, raw_payload=raw,
    ))
