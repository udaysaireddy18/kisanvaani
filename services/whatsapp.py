"""WhatsApp Cloud API service helpers.

Provides utilities for sending text messages and downloading media from
the WhatsApp Cloud API. All credentials are read from config.py / .env.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

import requests

from config import (
    MEDIA_DIR,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_API_BASE_URL,
    WHATSAPP_API_VERSION,
    WHATSAPP_PHONE_NUMBER_ID,
)

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = 20


class WhatsAppAPIError(RuntimeError):
    """Raised when the WhatsApp Cloud API returns an error."""


def _headers() -> dict[str, str]:
    """Build authorization headers for WhatsApp Cloud API requests."""
    return {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _messages_url() -> str:
    """Return the messages endpoint for the configured phone number."""
    base = WHATSAPP_API_BASE_URL.rstrip("/")
    return f"{base}/{WHATSAPP_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"


def send_text(to: str, body: str) -> dict[str, Any]:
    """Send a WhatsApp text message. Returns API response JSON."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    try:
        resp = requests.post(_messages_url(), headers=_headers(), json=payload, timeout=REQUEST_TIMEOUT)
        data = resp.json() if resp.content else {}
        if not resp.ok:
            logger.error("WhatsApp send_text failed: status=%s body=%s", resp.status_code, data)
            raise WhatsAppAPIError(f"send_text failed: {resp.status_code}")
        logger.info("WhatsApp text sent to=%s message_id=%s", to, _extract_sent_id(data))
        return data
    except requests.RequestException as exc:
        logger.exception("WhatsApp send_text request error for to=%s", to)
        raise WhatsAppAPIError("send_text request failed") from exc


def _extract_sent_id(data: dict[str, Any]) -> str | None:
    """Extract outbound WhatsApp message ID from API response."""
    messages = data.get("messages") or []
    if messages and isinstance(messages[0], dict):
        return messages[0].get("id")
    return None


def get_media_url(media_id: str) -> str:
    """Resolve a WhatsApp media ID to a temporary download URL."""
    base = WHATSAPP_API_BASE_URL.rstrip("/")
    url = f"{base}/{WHATSAPP_API_VERSION}/{media_id}"
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}, timeout=REQUEST_TIMEOUT)
        data = resp.json() if resp.content else {}
        if not resp.ok or "url" not in data:
            logger.error("WhatsApp get_media_url failed: status=%s body=%s", resp.status_code, data)
            raise WhatsAppAPIError(f"get_media_url failed: {resp.status_code}")
        return data["url"]
    except requests.RequestException as exc:
        logger.exception("WhatsApp get_media_url request error for media_id=%s", media_id)
        raise WhatsAppAPIError("get_media_url request failed") from exc


def download_media(media_id: str, media_type: str = "file") -> dict[str, Any]:
    """Download WhatsApp media to MEDIA_DIR. Returns metadata dict."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    media_url = get_media_url(media_id)
    try:
        resp = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            logger.error("WhatsApp media download failed: status=%s media_id=%s", resp.status_code, media_id)
            raise WhatsAppAPIError(f"download_media failed: {resp.status_code}")
        mime_type = resp.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()
        ext = _extension_for(media_type, mime_type)
        filename = f"{media_id}{ext}".replace("/", "_").replace("\\", "_")
        file_path = MEDIA_DIR / filename
        file_path.write_bytes(resp.content)
        logger.info("Downloaded media media_id=%s path=%s", media_id, file_path)
        return {
            "media_id": media_id,
            "file_path": str(file_path),
            "mime_type": mime_type,
            "size": len(resp.content),
        }
    except requests.RequestException as exc:
        logger.exception("WhatsApp download_media request error for media_id=%s", media_id)
        raise WhatsAppAPIError("download_media request failed") from exc


def _extension_for(media_type: str, mime_type: str) -> str:
    """Pick a file extension from mime type or WhatsApp media type."""
    ext = mimetypes.guess_extension(mime_type) or ""
    if ext == ".jpe":
        ext = ".jpg"
    if ext:
        return ext
    defaults = {"image": ".jpg", "audio": ".ogg", "video": ".mp4", "document": ".bin"}
    return defaults.get(media_type, ".bin")
