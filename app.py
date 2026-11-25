"""Flask application entry point for KisanVaani.

Provides:
- WhatsApp Cloud API webhook: GET/POST /webhook
- Public web demo UI: GET /
- Web API for demo/operator flow: /api/*
The web demo reuses the same extraction, claim flow, and PDF services.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file

from config import FLASK_DEBUG, FLASK_HOST, FLASK_PORT, WHATSAPP_VERIFY_TOKEN
from db.init_db import init_db
from db.models import Claim, Media, Message
from db.session import session_scope
from services.claim_flow import process_incoming_message
from services.pdf_generator import PDFGenerationError, generate_claim_pdf
from services.web_api import (
    get_claim_detail,
    list_claims,
    mark_pdf_generated,
    process_web_photo,
    process_web_text,
    update_claim_details,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")

# Cloud hosts often have an ephemeral filesystem, so the database file created
# during the build step may not exist at runtime. Initialize tables on startup.
init_db()


@app.get("/health")
def health() -> tuple[dict, int]:
    """Basic health check endpoint."""
    return jsonify({"status": "ok", "service": "kisanvaani"}), 200


@app.get("/")
def home() -> str:
    """Render the public web demo page."""
    return render_template("index.html")


@app.get("/webhook")
def verify_webhook() -> tuple[str | Response, int]:
    """Verify WhatsApp webhook subscription with Meta."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")

    if mode == "subscribe" and token and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return challenge, 200

    logger.warning("Webhook verification failed mode=%s token_valid=%s", mode, token == WHATSAPP_VERIFY_TOKEN)
    return "Forbidden", 403


@app.post("/webhook")
def receive_webhook() -> tuple[dict, int]:
    """Receive WhatsApp webhook events, log them, and acknowledge receipt."""
    payload = request.get_json(silent=True) or {}
    logger.info("Incoming webhook payload: %s", payload)

    for message, phone in iter_whatsapp_messages(payload):
        handle_incoming_message(message, phone, payload)
    return jsonify({"status": "received"}), 200


@app.get("/api/claims")
def api_claims() -> tuple[dict, int]:
    """List recent claims for web dashboard view."""
    try:
        return jsonify({"claims": list_claims()}), 200
    except Exception:
        logger.exception("Failed to list claims")
        return jsonify({"error": "Failed to load claims"}), 500


@app.get("/api/claims/<claim_id>")
def api_claim_detail(claim_id: str) -> tuple[dict, int]:
    """Get one claim by ID."""
    try:
        claim = get_claim_detail(claim_id)
        if not claim:
            return jsonify({"error": "Claim not found"}), 404
        return jsonify({"claim": claim}), 200
    except Exception:
        logger.exception("Failed to get claim claim_id=%s", claim_id)
        return jsonify({"error": "Failed to load claim"}), 500


@app.put("/api/claims/<claim_id>/details")
def api_update_claim_details(claim_id: str) -> tuple[dict, int]:
    """Save corrected crop/damage/village/date values from the review card."""
    body = request.get_json(silent=True) or {}
    language = str(body.get("language") or "hi").strip()
    try:
        result = update_claim_details(claim_id=claim_id, fields=body, language=language)
        return jsonify(result), 200
    except LookupError:
        return jsonify({"error": "Claim not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("Failed to update claim details claim_id=%s", claim_id)
        return jsonify({"error": "Failed to save details"}), 500


@app.post("/api/web/messages")
def api_web_message() -> tuple[dict, int]:
    """Handle web chat text message using the same claim flow logic."""
    body = request.get_json(silent=True) or {}
    phone = str(body.get("phone") or "").strip()
    message = str(body.get("message") or "").strip()
    claim_id = str(body.get("claim_id") or "").strip() or None
    language = str(body.get("language") or "hi").strip()
    if not phone or not message:
        return jsonify({"error": "phone and message are required"}), 400
    try:
        result = process_web_text(phone=phone, text=message, claim_id=claim_id, language=language)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("Web message processing failed phone=%s claim_id=%s", phone, claim_id)
        return jsonify({"error": "Failed to process message"}), 500


@app.post("/api/web/photos")
def api_web_photo() -> tuple[dict, int]:
    """Handle web photo upload and attach it to a claim."""
    phone = str(request.form.get("phone") or "").strip()
    claim_id = str(request.form.get("claim_id") or "").strip() or None
    language = str(request.form.get("language") or "hi").strip()
    photo = request.files.get("photo")
    if not phone or not photo:
        return jsonify({"error": "phone and photo are required"}), 400
    try:
        result = process_web_photo(phone=phone, photo=photo, claim_id=claim_id, language=language)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("Web photo upload failed phone=%s claim_id=%s", phone, claim_id)
        return jsonify({"error": "Failed to upload photo"}), 500


@app.post("/api/claims/<claim_id>/pdf")
def api_generate_pdf(claim_id: str) -> tuple[dict, int]:
    """Generate a claim PDF from web/operator UI."""
    try:
        with session_scope() as session:
            claim = session.get(Claim, claim_id)
            if not claim:
                return jsonify({"error": "Claim not found"}), 404
            photos = session.query(Media).filter(Media.claim_id == claim.id, Media.media_type == "image").all()
            if claim.missing_fields or len(photos) < 1:
                return jsonify({"error": "Claim must have all fields and at least 1 photo"}), 400
            pdf_path = generate_claim_pdf(claim, [m.file_path for m in photos])

        updated = mark_pdf_generated(claim_id, pdf_path)
        return jsonify({"claim": updated, "pdf_path": pdf_path}), 200
    except PDFGenerationError:
        return jsonify({"error": "PDF generation failed"}), 500
    except Exception:
        logger.exception("PDF generation endpoint failed claim_id=%s", claim_id)
        return jsonify({"error": "Failed to generate PDF"}), 500


@app.get("/api/claims/<claim_id>/pdf")
def api_download_pdf(claim_id: str) -> Response | tuple[dict, int]:
    """Download an existing generated PDF."""
    try:
        claim = get_claim_detail(claim_id)
        if not claim:
            return jsonify({"error": "Claim not found"}), 404
        pdf_path = claim.get("pdf_path")
        if not pdf_path or not Path(pdf_path).exists():
            return jsonify({"error": "PDF not generated yet"}), 404
        return send_file(pdf_path, mimetype="application/pdf", as_attachment=True, download_name=Path(pdf_path).name)
    except Exception:
        logger.exception("PDF download failed claim_id=%s", claim_id)
        return jsonify({"error": "Failed to download PDF"}), 500


def iter_whatsapp_messages(payload: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Extract WhatsApp message objects and sender phone from webhook payload."""
    results: list[tuple[dict[str, Any], str]] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for message in value.get("messages", []) or []:
                phone = str(message.get("from") or "").strip()
                if phone:
                    results.append((message, phone))
    return results


def is_duplicate_message(whatsapp_message_id: str | None) -> bool:
    """Check whether a WhatsApp message ID has already been processed."""
    if not whatsapp_message_id:
        return False
    try:
        with session_scope() as session:
            existing = session.query(Message.id).filter_by(whatsapp_message_id=whatsapp_message_id).first()
            return existing is not None
    except Exception:
        logger.exception("Idempotency check failed for whatsapp_message_id=%s", whatsapp_message_id)
        return False


def handle_incoming_message(message: dict[str, Any], phone: str, raw_payload: dict[str, Any]) -> None:
    """Handle a single inbound WhatsApp message with idempotency and logging."""
    msg_id = str(message.get("id") or "").strip() or None
    msg_type = str(message.get("type") or "unknown").strip().lower()

    if is_duplicate_message(msg_id):
        logger.info("Duplicate webhook ignored phone=%s type=%s msg_id=%s", phone, msg_type, msg_id)
        return

    logger.info("Incoming message phone=%s type=%s msg_id=%s", phone, msg_type, msg_id)
    process_incoming_message(message, phone, raw_payload)


if __name__ == "__main__":
    logger.info("Starting KisanVaani on %s:%s", FLASK_HOST, FLASK_PORT)
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
