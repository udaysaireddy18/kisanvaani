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

# Bot replies by language. Web users pick a language; WhatsApp stays on Hindi
# unless a language is passed explicitly.
REPLIES: dict[str, dict[str, str]] = {
    "hi": {
        "ask_crop": "Kaunsi fasal kharab hui hai? (jaise: ganna, gehu, dhan)",
        "ask_damage": "Fasal ko kya nuksan hua? (jaise: barish, sukhna, keede, aag)",
        "ask_village": "Aapka gaon/village ka naam kya hai?",
        "ask_date": "Fasal kab kharab hui? Date bataiye (DD/MM/YYYY).",
        "need_all": "Kripya poori jankari bhejein: fasal, nuksan ka prakar, gaon, aur date (DD/MM/YYYY).",
        "ask_photo": "Dhanyavaad. Kripya 1-3 nuksan ki photo bhejein.",
        "ready": "Aapka claim tayyar hai. Claim ID: {claim_id}. Operator dashboard se PDF generate kiya jayega.",
        "unsupported": "Kripya text, voice note, ya photo bhejein taaki hum aapka claim bana sakein.",
    },
    "en": {
        "ask_crop": "Which crop was damaged? (e.g. sugarcane, wheat, rice)",
        "ask_damage": "What kind of damage happened? (e.g. rain, drought, pests, fire)",
        "ask_village": "What is your village name?",
        "ask_date": "When did the damage happen? Please give the date (DD/MM/YYYY).",
        "need_all": "Please send all details: crop, damage type, village, and date (DD/MM/YYYY).",
        "ask_photo": "Thank you. Please upload 1-3 photos of the damage.",
        "ready": "Your claim is ready. Claim ID: {claim_id}. The operator will generate the PDF.",
        "unsupported": "Please send text, a voice note, or a photo so we can create your claim.",
    },
    "te": {
        "ask_crop": "ఏ పంట దెబ్బతింది? (ఉదా: చెరకు, గోధుమ, వరి)",
        "ask_damage": "పంటకు ఏమైంది? (ఉదా: వర్షం, కరువు, కీటకాలు, అగ్ని)",
        "ask_village": "మీ గ్రామం పేరు ఏమిటి?",
        "ask_date": "నష్టం ఎప్పుడు జరిగింది? తేదీ చెప్పండి (DD/MM/YYYY).",
        "need_all": "దయచేసి అన్ని వివరాలు పంపండి: పంట, నష్టం రకం, గ్రామం, తేదీ (DD/MM/YYYY).",
        "ask_photo": "ధన్యవాదాలు. దయచేసి నష్టం యొక్క 1-3 ఫోటోలు అప్\u200dలోడ్ చేయండి.",
        "ready": "మీ క్లెయిమ్ సిద్ధంగా ఉంది. క్లెయిమ్ ID: {claim_id}. ఆపరేటర్ PDF ని రూపొందిస్తారు.",
        "unsupported": "మీ క్లెయిమ్ కోసం దయచేసి టెక్స్ట్, వాయిస్ నోట్ లేదా ఫోటో పంపండి.",
    },
    "ta": {
        "ask_crop": "ஏது பயிர் சேதமடைந்தது? (உது: கரும்பு, கோதுமை, அரிசி)",
        "ask_damage": "பயிருக்கு என்ன சேதம் ஏற்பட்டது? (உது: மழை, வறட்சி, பூச்சிகள், தீ)",
        "ask_village": "உங்கள் கிராமம் பெயர் என்ன?",
        "ask_date": "சேதம் எப்போது நடந்தது? தேதி கூறுங்கள் (DD/MM/YYYY).",
        "need_all": "தயவுசெய்து அனைத்து விவரங்களையும் அனுப்புங்கள்: பயிர், சேத வகை, கிராமம், தேதி (DD/MM/YYYY).",
        "ask_photo": "நன்றி. சேதத்தின் 1-3 படங்களை பதிவேற்றம் செய்யுங்கள்.",
        "ready": "உங்கள் க்ளெயிம் தயாராக உள்ளது. க்ளெயிம் ID: {claim_id}. ஆபரேட்டர் PDF ஐ உருவாக்குவார்.",
        "unsupported": "உங்கள் க்ளெயிமுக்கு தயவுசெய்து உரை, குரல் குறிப்பு அல்லது படம் அனுப்புங்கள்.",
    },
    "bn": {
        "ask_crop": "কোন ফসল নষ্ট হয়েছে? (উদা: আখ, গম, ধান)",
        "ask_damage": "ফসলের কী ক্ষতি হয়েছে? (উদা: বৃষ্টি, খরা, কীটপতঙ্গ, আগুন)",
        "ask_village": "আপনার গ্রামের নাম কী?",
        "ask_date": "ক্ষতি কখন হয়েছে? তারিখ বলুন (DD/MM/YYYY).",
        "need_all": "অনুগ্রহ করে সব তথ্য পাঠান: ফসল, ক্ষতির ধরন, গ্রাম এবং তারিখ (DD/MM/YYYY).",
        "ask_photo": "ধন্যবাদ। অনুগ্রহ করে ক্ষতির 1-3টি ছবি আপলোড করুন।",
        "ready": "আপনার ক্লেইম প্রস্তুত। ক্লেইম ID: {claim_id}. অপারেটর PDF তৈরি করবেন।",
        "unsupported": "আপনার ক্লেইমের জন্য অনুগ্রহ করে টেক্সট, ভয়েস নোট বা ছবি পাঠান।",
    },
    "mr": {
        "ask_crop": "कोणत्या पिकाचे नुकसान झाले? (उदा: ऊस, गहू, तांदूळ)",
        "ask_damage": "पिकाला काय नुकसान झाले? (उदा: पाऊस, दुष्काळ, कीडे, आग)",
        "ask_village": "तुमच्या गावाचे नाव काय आहे?",
        "ask_date": "नुकसान केव्हा झाले? तारीख सांगा (DD/MM/YYYY).",
        "need_all": "कृपया सर्व माहिती पाठवा: पीक, नुकसानाचा प्रकार, गाव आणि तारीख (DD/MM/YYYY).",
        "ask_photo": "धन्यवाद. कृपया नुकसानाचे 1-3 फोटो अपलोड करा.",
        "ready": "तुमचा क्लेम तयार आहे. क्लेम ID: {claim_id}. ऑपरेटर PDF तयार करेल.",
        "unsupported": "तुमच्या क्लेमसाठी कृपया टेक्स्ट, व्हॉइस नोट किंवा फोटो पाठवा.",
    },
}


def normalize_language(language: str | None) -> str:
    """Return a supported language code, defaulting to Hindi."""
    value = (language or "").strip().lower()
    return value if value in REPLIES else "hi"


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


def _next_reply(session: Any, claim: Claim, language: str = "hi") -> list[str]:
    """Decide next bot replies based on claim state and missing info."""
    lang = normalize_language(language)
    texts = REPLIES[lang]
    missing = list(claim.missing_fields or [])
    photos = _count_photos(session, claim.id)

    if missing and claim.followup_count < MAX_FOLLOWUPS:
        claim.followup_count += 1
        return [_question_for(missing[0], lang)]

    if missing:
        return [texts["need_all"]]

    if photos < 1:
        if claim.status != ClaimStatus.READY:
            claim.status = ClaimStatus.COLLECTING
        return [texts["ask_photo"]]

    if claim.status != ClaimStatus.PDF_GENERATED:
        claim.status = ClaimStatus.READY
    return [texts["ready"].format(claim_id=claim.id)]


def _question_for(field: str, language: str = "hi") -> str:
    """Return a clarifying question for a missing field."""
    texts = REPLIES[normalize_language(language)]
    key = {
        "crop": "ask_crop",
        "damage": "ask_damage",
        "village": "ask_village",
        "date": "ask_date",
    }.get(field, "need_all")
    return texts[key]


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
