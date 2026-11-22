"""PDF claim summary generator for KisanVaani.

Generates a one-page insurer-ready PDF using ReportLab with claim fields,
photo thumbnails, timestamp, and claim ID.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from config import PDF_DIR

logger = logging.getLogger(__name__)


class PDFGenerationError(RuntimeError):
    """Raised when claim PDF generation fails."""


def generate_claim_pdf(claim: Any, photos: list[str] | None = None) -> str:
    """Generate a one-page claim PDF and return its file path."""
    try:
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{claim.id}.pdf"
        output_path = PDF_DIR / filename
        photos = [p for p in (photos or []) if p and Path(p).exists()][:3]

        c = canvas.Canvas(str(output_path), pagesize=A4)
        width, height = A4
        _draw_header(c, width, height)
        _draw_fields(c, claim, width, height)
        _draw_photos(c, photos, width)
        _draw_footer(c, claim, width)
        c.showPage()
        c.save()

        logger.info("Generated claim PDF claim_id=%s path=%s", claim.id, output_path)
        return str(output_path)
    except Exception as exc:
        logger.exception("PDF generation failed claim_id=%s", getattr(claim, "id", "unknown"))
        raise PDFGenerationError("Failed to generate claim PDF") from exc


def _draw_header(c: canvas.Canvas, width: float, height: float) -> None:
    """Draw PDF title and branding."""
    c.setFillColor(colors.HexColor("#1B5E20"))
    c.rect(0, height - 28 * mm, width, 28 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20 * mm, height - 16 * mm, "KisanVaani - Crop Loss Claim Summary")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, height - 23 * mm, "Insurer-ready claim packet (MVP)")


def _draw_fields(c: canvas.Canvas, claim: Any, width: float, height: float) -> None:
    """Draw claim fields in a simple table layout."""
    y = height - 42 * mm
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, y, "Claim Details")
    y -= 8 * mm

    rows = [
        ("Claim ID", getattr(claim, "id", "")),
        ("Farmer Phone", getattr(claim, "farmer_phone", "")),
        ("Crop", _display(getattr(claim, "crop", None))),
        ("Damage Type", _display(getattr(claim, "damage_type", None))),
        ("Village/Location", _display(getattr(claim, "village", None))),
        ("Incident Date", _display(getattr(claim, "incident_date", None))),
        ("Status", _status(getattr(claim, "status", ""))),
        ("Confidence", f"{float(getattr(claim, 'confidence', 0.0)):.2f}"),
    ]

    c.setFont("Helvetica", 10)
    for label, value in rows:
        c.setFillColor(colors.HexColor("#E8F5E9"))
        c.rect(20 * mm, y - 5 * mm, 70 * mm, 7 * mm, fill=1, stroke=0)
        c.rect(90 * mm, y - 5 * mm, width - 110 * mm, 7 * mm, fill=0, stroke=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(22 * mm, y - 3.2 * mm, label)
        c.setFont("Helvetica", 10)
        c.drawString(92 * mm, y - 3.2 * mm, str(value))
        y -= 8.5 * mm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, y - 2 * mm, "Damage Photos")
    c.setStrokeColor(colors.grey)
    c.line(20 * mm, y - 4 * mm, width - 20 * mm, y - 4 * mm)


def _draw_photos(c: canvas.Canvas, photos: list[str], width: float) -> None:
    """Draw up to 3 photo thumbnails."""
    y = 82 * mm
    box_w, box_h = 52 * mm, 45 * mm
    gap = 6 * mm
    x = 20 * mm
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.black)

    if not photos:
        c.drawString(20 * mm, y + 20 * mm, "No photos attached.")
        return

    for idx, photo in enumerate(photos, start=1):
        c.setStrokeColor(colors.grey)
        c.rect(x, y, box_w, box_h, fill=0, stroke=1)
        try:
            img = ImageReader(photo)
            c.drawImage(img, x + 1 * mm, y + 1 * mm, box_w - 2 * mm, box_h - 2 * mm,
                        preserveAspectRatio=True, anchor="c")
        except Exception:
            logger.exception("Failed to render photo in PDF: %s", photo)
            c.drawString(x + 3 * mm, y + box_h / 2, "Photo unavailable")
        c.drawString(x, y - 5 * mm, f"Photo {idx}")
        x += box_w + gap
        if x + box_w > width - 20 * mm:
            break


def _draw_footer(c: canvas.Canvas, claim: Any, width: float) -> None:
    """Draw timestamp/footer."""
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    created = getattr(claim, "created_at", None)
    created_str = created.strftime("%d/%m/%Y %H:%M:%S") if hasattr(created, "strftime") else str(created or "")
    c.setStrokeColor(colors.grey)
    c.line(20 * mm, 18 * mm, width - 20 * mm, 18 * mm)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.black)
    c.drawString(20 * mm, 13 * mm, f"Generated: {ts} | Claim Created: {created_str}")
    c.drawRightString(width - 20 * mm, 13 * mm, "KisanVaani MVP")


def _display(value: Any) -> str:
    """Display a field value or a dash."""
    text = str(value or "").strip()
    return text if text else "-"


def _status(value: Any) -> str:
    """Normalize claim status for display."""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "-")
