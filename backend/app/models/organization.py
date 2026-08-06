from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Organization(Base):
    """Phase 1 multi-tenant seam (see
    docs/wiki/multi-tenant-provisioning-and-document-archive.md): a real
    customer/organization with its own Google Sheet. Deliberately minimal --
    self-serve provisioning, per-org Telegram routing, and automated
    supplier-catalog import are all explicitly deferred until a second real
    organization exists.
    """

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    google_spreadsheet_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_drive_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
