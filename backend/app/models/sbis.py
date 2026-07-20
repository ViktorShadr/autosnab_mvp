from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SbisSyncState(Base):
    __tablename__ = "sbis_sync_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_datetime_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class SbisDocument(Base):
    __tablename__ = "sbis_documents"
    __table_args__ = (
        UniqueConstraint("sbis_document_id", name="uq_sbis_document"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sbis_document_id: Mapped[str] = mapped_column(String(128), index=True)
    document_type: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    document_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    document_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    counterparty_inn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="discovered", index=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_id: Mapped[int | None] = mapped_column(ForeignKey("receivings.id"), nullable=True, index=True)
    raw_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class SbisArtifact(Base):
    __tablename__ = "sbis_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "sbis_document_id",
            "artifact_kind",
            "source_attachment_id",
            name="uq_sbis_artifact",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sbis_document_id: Mapped[int] = mapped_column(ForeignKey("sbis_documents.id"), index=True)
    artifact_kind: Mapped[str] = mapped_column(String(64), index=True)
    source_attachment_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_path: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SbisDelivery(Base):
    __tablename__ = "sbis_deliveries"
    __table_args__ = (
        UniqueConstraint("sbis_document_id", "delivery_type", name="uq_sbis_delivery"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sbis_document_id: Mapped[int] = mapped_column(ForeignKey("sbis_documents.id"), index=True)
    delivery_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class SbisLease(Base):
    __tablename__ = "sbis_leases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
