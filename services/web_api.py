"""Web API helpers for the public/demo web interface.

Reuses existing claim extraction, claim flow state machine, and PDF services.
This keeps the web demo behavior aligned with the future WhatsApp bot flow.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from config import MEDIA_DIR
from db.models import Claim, ClaimEvent, ClaimStatus, Media, Message, MessageDirection
from db.session import session_scope
from services.claim_flow import (
    REPLIES,
    _apply_extraction,
    _count_photos,
    _next_reply,
    _outbound_messages,
    normalize_language,
    record_claim_event,
)
from services.extractor import extract_fields, normalize_date

logger = logging.getLogger(__name__)
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
REVIEW_FIELD_LIMITS = {"crop": 64, "damage_type": 64, "village": 128, "incident_date": 32}
MIN_IMAGE_WIDTH = 480
MIN_IMAGE_HEIGHT = 360
MIN_IMAGE_BYTES = 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
BLUR_EDGE_MEAN_MIN = 8.0


class PhotoQualityWarning(Exception):
    """A photo is usable but failed a soft quality check (for example, blur)."""


def process_web_text(phone: str, text: str, claim_id: str | None = None,
                     language: str = "hi") -> dict[str, Any]:
    """Process a web text message through the existing claim flow logic."""
    phone = (phone or "").strip()
    text = (text or "").strip()
    if not phone or not text:
        raise ValueError("phone and message are required")

    extraction = extract_fields(text)
    with session_scope() as session:
        claim = _get_open_claim(session, phone, claim_id)
        asked_field = (claim.missing_fields or [None])[0]
        _save_web_message(session, claim, phone, "text", text, transcript=None)
        _apply_extraction(claim, extraction)
        _apply_direct_answer(claim, asked_field, text)
        replies = _next_reply(session, claim, normalize_language(language))
        session.add_all(_outbound_messages(claim, phone, replies))
        session.flush()
        return {"replies": replies, "claim": serialize_claim(session, claim)}


def update_claim_details(claim_id: str, fields: dict[str, Any], language: str = "hi") -> dict[str, Any]:
    """Save operator-corrected claim fields from the web review card.

    Values are trimmed, the date is normalized to DD/MM/YYYY, and the claim's
    missing fields/confidence/status are recalculated from the edited values.
    """
    claim_id = (claim_id or "").strip()
    if not claim_id:
        raise ValueError("claim_id is required")

    raw_values = {
        "crop": str(fields.get("crop") or "").strip(),
        "damage_type": str(fields.get("damage_type") or fields.get("damage") or "").strip(),
        "village": str(fields.get("village") or "").strip(),
        "incident_date": str(fields.get("incident_date") or fields.get("date") or "").strip(),
    }
    for name, limit in REVIEW_FIELD_LIMITS.items():
        if len(raw_values[name]) > limit:
            raise ValueError(f"{name} is too long (max {limit} characters)")

    date_value = normalize_date(raw_values["incident_date"]) if raw_values["incident_date"] else ""
    if raw_values["incident_date"] and not date_value:
        raise ValueError("Invalid date. Use DD/MM/YYYY, for example 12/11/2026.")
    raw_values["incident_date"] = date_value or ""

    with session_scope() as session:
        claim = session.get(Claim, claim_id)
        if not claim:
            raise LookupError("Claim not found")
        if claim.status == ClaimStatus.PDF_GENERATED:
            raise ValueError("PDF already generated. Start a new demo claim to edit details.")

        was_complete = not bool(claim.missing_fields)
        previous_status = claim.status
        old_values = (claim.crop, claim.damage_type, claim.village, claim.incident_date)
        claim.crop = raw_values["crop"] or None
        claim.damage_type = raw_values["damage_type"] or None
        claim.village = raw_values["village"] or None
        claim.incident_date = raw_values["incident_date"] or None

        missing = [key for key, value in (
            ("crop", raw_values["crop"]),
            ("damage", raw_values["damage_type"]),
            ("village", raw_values["village"]),
            ("date", raw_values["incident_date"]),
        ) if not value]
        claim.missing_fields = missing
        claim.confidence = round((4 - len(missing)) / 4, 2)
        claim.followup_count = 0

        photos = _count_photos(session, claim.id)
        claim.status = ClaimStatus.READY if not missing and photos >= 1 else ClaimStatus.COLLECTING

        new_values = (claim.crop, claim.damage_type, claim.village, claim.incident_date)
        if not missing and not was_complete:
            record_claim_event(claim, "Details received", ClaimStatus.COLLECTING.value)
        elif new_values != old_values:
            record_claim_event(claim, "Details updated", claim.status.value)
        if claim.status == ClaimStatus.READY and previous_status != ClaimStatus.READY:
            record_claim_event(claim, "Claim ready", ClaimStatus.READY.value)

        texts = REPLIES[normalize_language(language)]
        if missing:
            replies = [texts["need_all"]]
        elif photos < 1:
            replies = [texts["details_saved_need_photo"]]
        else:
            replies = [texts["details_saved_ready"].format(claim_id=claim.id)]
        session.add_all(_outbound_messages(claim, claim.farmer_phone, replies))
        session.flush()

        logger.info(
            "Updated claim details claim_id=%s missing=%s status=%s",
            claim.id, claim.missing_fields, claim.status.value,
        )
        return {"replies": replies, "claim": serialize_claim(session, claim)}


SHORT_ANSWER_MAX = 40
VILLAGE_PREFIX_RE = re.compile(
    r"^\s*(?:village|gaon|gaav|gram|गाँव|गांव|ग्राम)\s+", re.IGNORECASE
)


def _apply_direct_answer(claim: Claim, asked_field: str | None, text: str) -> None:
    """Use a short follow-up reply (e.g. just a village name) for the asked field."""
    if not asked_field or asked_field not in (claim.missing_fields or []):
        return
    # Only village needs this: crop/damage/date have keyword/date extractors.
    if asked_field != "village" or len(text) > SHORT_ANSWER_MAX:
        return
    value = VILLAGE_PREFIX_RE.sub("", text).strip(" ,.!?।:-")
    if not value:
        return
    logger.info("Applying direct village answer claim_id=%s value=%s", claim.id, value)
    _apply_extraction(claim, {
        "crop": claim.crop or "",
        "damage": claim.damage_type or "",
        "village": value,
        "date": claim.incident_date or "",
    })


def inspect_photo(data: bytes, filename: str, force: bool = False) -> dict[str, Any]:
    """Validate an uploaded image and return simple quality metrics.

    Hard failures (corrupt file, wrong format, wrong size) raise ValueError.
    A likely-blurry image raises PhotoQualityWarning unless force=True.
    """
    size = len(data)
    if size < MIN_IMAGE_BYTES:
        raise ValueError("Photo is empty or too small to be useful.")
    if size > MAX_IMAGE_BYTES:
        raise ValueError("Photo is too large. Maximum size is 10 MB.")

    ext = Path(secure_filename(filename)).suffix.lower() or ".jpg"
    if ext not in ALLOWED_IMAGE_EXT:
        raise ValueError("Only image files are allowed (.jpg, .png, .webp)")

    try:
        with Image.open(BytesIO(data)) as probe:
            probe.verify()
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            image_format = (image.format or "").upper()
            edges = image.convert("L").resize((256, 256)).filter(ImageFilter.FIND_EDGES)
            sharpness = round(ImageStat.Stat(edges).mean[0], 2)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Invalid or corrupted image file.") from exc

    if image_format not in {"JPEG", "PNG", "WEBP"}:
        raise ValueError("Only JPG, PNG, or WEBP images are supported.")
    if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
        raise ValueError(
            f"Photo is too small ({width}x{height}). Minimum is {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT} pixels."
        )

    quality = {
        "width": width,
        "height": height,
        "bytes": size,
        "format": image_format,
        "sharpness": sharpness,
    }
    if sharpness < BLUR_EDGE_MEAN_MIN and not force:
        raise PhotoQualityWarning(
            f"Photo looks blurry (sharpness {sharpness}). Upload a clearer photo or confirm to use this one."
        )
    return quality


def process_web_photo(phone: str, photo: FileStorage, claim_id: str | None = None,
                      language: str = "hi", force: bool = False) -> dict[str, Any]:
    """Save an uploaded photo and attach it to a claim."""
    phone = (phone or "").strip()
    if not phone:
        raise ValueError("phone is required")
    if not photo or not photo.filename:
        raise ValueError("photo file is required")

    data = photo.read()
    quality = inspect_photo(data, photo.filename, force=force)

    ext = Path(secure_filename(photo.filename)).suffix.lower() or ".jpg"
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"web_{uuid.uuid4().hex}{ext}"
    file_path = MEDIA_DIR / filename
    file_path.write_bytes(data)
    logger.info("Saved web photo phone=%s path=%s quality=%s", phone, file_path, quality)

    with session_scope() as session:
        claim = _get_open_claim(session, phone, claim_id)
        _save_web_message(session, claim, phone, "image", filename, transcript=None)
        first_photo = _count_photos(session, claim.id) == 0
        session.add(Media(
            claim_id=claim.id, media_type="image", whatsapp_media_id=None,
            file_path=str(file_path), mime_type=photo.mimetype or "image/jpeg",
        ))
        session.flush()  # Make the photo visible to _next_reply's photo count.
        if first_photo:
            record_claim_event(claim, "Photos uploaded", ClaimStatus.COLLECTING.value)
        replies = _next_reply(session, claim, normalize_language(language))
        session.add_all(_outbound_messages(claim, phone, replies))
        session.flush()
        return {"replies": replies, "claim": serialize_claim(session, claim), "quality": quality}


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
        record_claim_event(claim, "PDF generated", ClaimStatus.PDF_GENERATED.value)
        session.flush()
        return serialize_claim(session, claim)


def _iso(value: Any) -> str | None:
    """Return an ISO timestamp for a datetime-like value."""
    return value.isoformat() if value else None


def _serialize_timeline(session: Any, claim: Claim) -> list[dict[str, Any]]:
    """Return status milestones, with a derived fallback for older claims."""
    events = (
        session.query(ClaimEvent)
        .filter(ClaimEvent.claim_id == claim.id)
        .order_by(ClaimEvent.created_at, ClaimEvent.id)
        .all()
    )
    if events:
        return [
            {"label": event.label, "status": event.status, "created_at": _iso(event.created_at)}
            for event in events
        ]

    timeline: list[dict[str, Any]] = [
        {"label": "Claim created", "status": ClaimStatus.NEW.value, "created_at": _iso(claim.created_at)}
    ]
    if not (claim.missing_fields or []):
        first_message = (
            session.query(Message)
            .filter(Message.claim_id == claim.id, Message.direction == MessageDirection.INBOUND)
            .order_by(Message.created_at)
            .first()
        )
        timeline.append({
            "label": "Details received",
            "status": ClaimStatus.COLLECTING.value,
            "created_at": _iso(first_message.created_at if first_message else claim.updated_at),
        })
    first_photo = (
        session.query(Media)
        .filter(Media.claim_id == claim.id, Media.media_type == "image")
        .order_by(Media.created_at)
        .first()
    )
    if first_photo:
        timeline.append({
            "label": "Photos uploaded",
            "status": ClaimStatus.COLLECTING.value,
            "created_at": _iso(first_photo.created_at),
        })
    if claim.status in (ClaimStatus.READY, ClaimStatus.PDF_GENERATED):
        timeline.append({
            "label": "Claim ready",
            "status": ClaimStatus.READY.value,
            "created_at": _iso(claim.updated_at),
        })
    if claim.status == ClaimStatus.PDF_GENERATED:
        timeline.append({
            "label": "PDF generated",
            "status": ClaimStatus.PDF_GENERATED.value,
            "created_at": _iso(claim.updated_at),
        })
    return timeline


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
        "timeline": _serialize_timeline(session, claim),
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
    record_claim_event(claim, "Claim created", ClaimStatus.NEW.value)
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
