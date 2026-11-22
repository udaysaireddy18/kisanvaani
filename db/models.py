"""SQLAlchemy models for KisanVaani.

Defines the core persistence tables:
- Claim: farmer claim lifecycle and extracted fields
- Message: inbound/outbound WhatsApp messages (idempotent on WhatsApp message_id)
- Media: stored audio/image files attached to claims/messages
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Return current UTC time as an aware datetime."""
    return datetime.now(timezone.utc)


def generate_claim_id() -> str:
    """Generate a short, human-readable claim ID."""
    return f"KV-{uuid.uuid4().hex[:10].upper()}"


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


class ClaimStatus(str, enum.Enum):
    """Claim lifecycle states."""

    NEW = "NEW"
    COLLECTING = "COLLECTING"
    READY = "READY"
    PDF_GENERATED = "PDF_GENERATED"


class MessageDirection(str, enum.Enum):
    """Direction of a WhatsApp message."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Claim(Base):
    """A farmer crop-damage claim tracked through the WhatsApp flow."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_claim_id)
    farmer_phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, native_enum=False, length=32),
        default=ClaimStatus.NEW,
        nullable=False,
        index=True,
    )

    crop: Mapped[str | None] = mapped_column(String(64), nullable=True)
    damage_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    village: Mapped[str | None] = mapped_column(String(128), nullable=True)
    incident_date: Mapped[str | None] = mapped_column(String(32), nullable=True)

    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    followup_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    media: Mapped[list["Media"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="Media.created_at"
    )

    def __repr__(self) -> str:
        return f"<Claim id={self.id} phone={self.farmer_phone} status={self.status}>"


class Message(Base):
    """A WhatsApp message associated with a claim."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("whatsapp_message_id", name="uq_messages_whatsapp_message_id"),
        Index("ix_messages_claim_phone", "claim_id", "phone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("claims.id", ondelete="CASCADE"), index=True, nullable=True
    )
    whatsapp_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, native_enum=False, length=16), nullable=False
    )
    phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    msg_type: Mapped[str] = mapped_column(String(32), nullable=False)  # text/audio/image/...
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    claim: Mapped["Claim | None"] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message id={self.id} claim_id={self.claim_id} type={self.msg_type}>"


class Media(Base):
    """A media file (audio/image) attached to a claim or message."""

    __tablename__ = "media"
    __table_args__ = (Index("ix_media_claim_type", "claim_id", "media_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("claims.id", ondelete="CASCADE"), index=True, nullable=False
    )
    message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("messages.id", ondelete="SET NULL"), index=True, nullable=True
    )
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)  # image/audio/document
    whatsapp_media_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    claim: Mapped["Claim"] = relationship(back_populates="media")

    def __repr__(self) -> str:
        return f"<Media id={self.id} claim_id={self.claim_id} type={self.media_type}>"
