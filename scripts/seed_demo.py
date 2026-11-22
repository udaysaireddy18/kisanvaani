"""Seed demo claims/messages/media for KisanVaani.

Run as: python -m scripts.seed_demo  (from kisanvaani/ directory)
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.init_db import init_db  # noqa: E402
from db.models import Claim, ClaimStatus, Media, Message, MessageDirection  # noqa: E402
from db.session import session_scope  # noqa: E402


def ensure_sample_assets() -> dict[str, list[str]]:
    """Create sample photos and a small sample audio placeholder if missing."""
    samples = PROJECT_ROOT / "samples"
    photos_dir = samples / "sample_photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    photo_specs = [
        ("damage_1.jpg", "Rain damage - sugarcane field", (120, 70, 40)),
        ("damage_2.jpg", "Flooded crop area", (80, 110, 60)),
        ("damage_3.jpg", "Pest damage - wheat leaves", (130, 120, 50)),
    ]
    photo_paths = []
    for name, label, color in photo_specs:
        path = photos_dir / name
        if not path.exists():
            img = Image.new("RGB", (900, 600), color=color)
            draw = ImageDraw.Draw(img)
            draw.rectangle([30, 30, 870, 570], outline=(255, 255, 255), width=6)
            draw.text((60, 70), "KisanVaani Sample Photo", fill=(255, 255, 255))
            draw.text((60, 120), label, fill=(255, 255, 255))
            draw.text((60, 500), datetime.now().strftime("%d/%m/%Y"), fill=(255, 255, 255))
            img.save(path, format="JPEG", quality=90)
        photo_paths.append(str(path))

    audio_path = samples / "sample_audio.mp3"
    # Keep existing placeholder or a real file if user replaced it.
    if not audio_path.exists():
        audio_path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")

    return {"photos": photo_paths, "audio": [str(audio_path)]}


def clear_existing_demo_claims(session) -> None:
    """Remove previously seeded demo claims for idempotent reseeding."""
    demo_phones = ["+919999000001", "+919999000002"]
    claims = session.query(Claim).filter(Claim.farmer_phone.in_(demo_phones)).all()
    for claim in claims:
        session.delete(claim)
    session.flush()


def seed_claims() -> None:
    """Insert two demo claims with messages and photos."""
    init_db()
    assets = ensure_sample_assets()
    now = datetime.now(timezone.utc)

    with session_scope() as session:
        clear_existing_demo_claims(session)

        claim1 = Claim(
            id="KV-DEMO0001",
            farmer_phone="+919999000001",
            status=ClaimStatus.READY,
            crop="sugarcane",
            damage_type="rain",
            village="Rampur",
            incident_date="12/11/2026",
            confidence=1.0,
            missing_fields=[],
            followup_count=1,
            created_at=now - timedelta(hours=3),
            updated_at=now - timedelta(hours=2),
        )
        session.add(claim1)
        session.flush()
        session.add_all([
            Message(claim_id=claim1.id, direction=MessageDirection.INBOUND, phone=claim1.farmer_phone,
                    msg_type="audio", content="sample_audio.mp3",
                    transcript="Meri ganne ki fasal barish se kharab ho gayi, village Rampur."),
            Message(claim_id=claim1.id, direction=MessageDirection.OUTBOUND, phone=claim1.farmer_phone,
                    msg_type="text", content="Fasal kab kharab hui? Date bataiye (DD/MM/YYYY)."),
            Message(claim_id=claim1.id, direction=MessageDirection.INBOUND, phone=claim1.farmer_phone,
                    msg_type="text", content="12/11/2026"),
            Message(claim_id=claim1.id, direction=MessageDirection.OUTBOUND, phone=claim1.farmer_phone,
                    msg_type="text", content="Dhanyavaad. Kripya 1-3 nuksan ki photo bhejein."),
            Message(claim_id=claim1.id, direction=MessageDirection.OUTBOUND, phone=claim1.farmer_phone,
                    msg_type="text", content=f"Aapka claim tayyar hai. Claim ID: {claim1.id}. Operator dashboard se PDF generate kiya jayega."),
        ])
        for p in assets["photos"][:2]:
            session.add(Media(claim_id=claim1.id, media_type="image", file_path=p, mime_type="image/jpeg"))

        claim2 = Claim(
            id="KV-DEMO0002",
            farmer_phone="+919999000002",
            status=ClaimStatus.COLLECTING,
            crop="wheat",
            damage_type="pest",
            village="",
            incident_date="20/11/2026",
            confidence=0.75,
            missing_fields=["village"],
            followup_count=1,
            created_at=now - timedelta(hours=1, minutes=30),
            updated_at=now - timedelta(minutes=30),
        )
        session.add(claim2)
        session.flush()
        session.add_all([
            Message(claim_id=claim2.id, direction=MessageDirection.INBOUND, phone=claim2.farmer_phone,
                    msg_type="text", content="Gehu ki fasal mein keede lag gaye hain, kal se dikkat hai."),
            Message(claim_id=claim2.id, direction=MessageDirection.OUTBOUND, phone=claim2.farmer_phone,
                    msg_type="text", content="Aapka gaon/village ka naam kya hai?"),
        ])
        session.add(Media(claim_id=claim2.id, media_type="image", file_path=assets["photos"][2], mime_type="image/jpeg"))

    print("Seeded demo claims: KV-DEMO0001 (READY), KV-DEMO0002 (COLLECTING)")
    print(f"Sample photos: {PROJECT_ROOT / 'samples' / 'sample_photos'}")
    print(f"Sample audio: {PROJECT_ROOT / 'samples' / 'sample_audio.mp3'}")


if __name__ == "__main__":
    seed_claims()
