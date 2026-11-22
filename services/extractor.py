"""Rule-based claim field extraction for KisanVaani.

Extracts crop, damage, village, and date from Hindi/English farmer messages.
Returns: {"crop": "", "damage": "", "village": "", "date": "", "missing": [], "confidence": 0-1}
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

CROP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sugarcane": ("ganna", "ganne", "ganne ki", "sugarcane"),
    "wheat": ("gehu", "gehun", "wheat"),
    "rice": ("dhan", "dhaan", "chawal", "rice", "paddy"),
    "cotton": ("kapas", "cotton"),
    "maize": ("makka", "makkaa", "maize", "corn"),
    "potato": ("aloo", "aaloo", "potato"),
    "onion": ("pyaz", "pyaaz", "onion"),
}

DAMAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "rain": ("barish", "baarish", "rain", "flood", "baadh", "baarh", "paani", "jalbharav"),
    "drought": ("sukhna", "sukha", "drought", "sookha"),
    "pest": ("keede", "keeda", "keet", "pest", "insect", "kida"),
    "fire": ("aag", "fire", "jal gaya", "jal gaye"),
    "storm": ("toofan", "andhi", "storm", "cyclone"),
    "hail": ("ole", "ola", "hail", "hailstorm"),
}


def extract_fields(text: str) -> dict[str, Any]:
    """Extract claim fields from text using deterministic rules."""
    raw = (text or "").strip()
    normalized = " ".join(raw.lower().split())
    logger.info("Extracting fields from text_len=%s", len(normalized))

    crop = _match_keyword(normalized, CROP_KEYWORDS)
    damage = _match_keyword(normalized, DAMAGE_KEYWORDS)
    village = _extract_village(raw, normalized)
    date = _extract_date(normalized)

    fields = {
        "crop": crop or "",
        "damage": damage or "",
        "village": village or "",
        "date": date or "",
    }
    missing = [k for k in ["crop", "damage", "village", "date"] if not fields[k]]
    confidence = round((4 - len(missing)) / 4, 2)
    result = {**fields, "missing": missing, "confidence": confidence}
    logger.info("Extraction result: %s", result)
    return result


def _match_keyword(text: str, mapping: dict[str, tuple[str, ...]]) -> str | None:
    """Return canonical name for the first matching keyword group."""
    for canonical, keywords in mapping.items():
        for kw in keywords:
            pattern = r"(?<![a-zA-Z0-9])" + re.escape(kw.lower()) + r"(?![a-zA-Z0-9])"
            if re.search(pattern, text, flags=re.IGNORECASE):
                return canonical
    return None


def _extract_village(raw: str, normalized: str) -> str | None:
    """Extract village/location using Hindi/English cues."""
    patterns = [
        r"\b(?:village|gaon|gaav|gram)\s+([A-Za-z][A-Za-z\s\-]{1,40})",
        r"\b(?:in|mein|me)\s+([A-Za-z][A-Za-z\s\-]{1,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_location(match.group(1))
        if candidate:
            return candidate
    # Fallback: look for "gaon" in normalized but capture original case token nearby
    return None


def _clean_location(value: str) -> str | None:
    """Clean a location candidate by trimming trailing noise."""
    cleaned = re.split(r"[,.!?]|(?:\bke\b|\bki\b|\bmein\b|\bme\b|\bse\b|\bpar\b)", value, maxsplit=1)[0]
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_")
    if not cleaned:
        return None
    # Avoid capturing common non-location words
    stop = {"fasal", "crop", "barish", "rain", "flood", "aaj", "kal", "today", "yesterday"}
    if cleaned.lower() in stop:
        return None
    return cleaned[:40].title()


def _extract_date(normalized: str) -> str | None:
    """Extract date as DD/MM/YYYY from explicit formats or relative words."""
    explicit = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", normalized)
    if explicit:
        return _format_date(explicit.group(1), explicit.group(2), explicit.group(3))

    today = datetime.now().date()
    if re.search(r"(?<![a-z])aaj(?![a-z])|\btoday\b", normalized):
        return today.strftime("%d/%m/%Y")
    if re.search(r"(?<![a-z])kal(?![a-z])|\byesterday\b", normalized):
        return (today - timedelta(days=1)).strftime("%d/%m/%Y")
    return None


def _format_date(day: str, month: str, year: str) -> str | None:
    """Normalize date components to DD/MM/YYYY if valid."""
    try:
        dd, mm = int(day), int(month)
        yyyy = int(year)
        if yyyy < 100:
            yyyy += 2000
        parsed = datetime(yyyy, mm, dd).date()
        return parsed.strftime("%d/%m/%Y")
    except ValueError:
        logger.warning("Invalid date components day=%s month=%s year=%s", day, month, year)
        return None


def merge_extraction(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge newly extracted fields into existing claim fields, preferring non-empty new values."""
    merged = {
        "crop": incoming.get("crop") or existing.get("crop") or "",
        "damage": incoming.get("damage") or existing.get("damage") or "",
        "village": incoming.get("village") or existing.get("village") or "",
        "date": incoming.get("date") or existing.get("date") or "",
    }
    missing = [k for k in ["crop", "damage", "village", "date"] if not merged[k]]
    merged["missing"] = missing
    merged["confidence"] = round((4 - len(missing)) / 4, 2)
    return merged
