import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow

_JSON = JSON().with_variant(JSONB(), "postgresql")


class AuditEvent(Base):
    """Append-only record of an administrative change.

    Written in the same transaction as the change. Actor and site are snapshots (no foreign keys), so
    the history stays readable after a user is renamed or a site is deleted.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(index=True, default=None)
    actor_email: Mapped[str] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(48), index=True)  # "<group>.<verb>", e.g. user.promote
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[str] = mapped_column(String(64))
    site_id: Mapped[uuid.UUID | None] = mapped_column(index=True, default=None)
    site_name: Mapped[str | None] = mapped_column(String(120), default=None)
    summary: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict] = mapped_column(_JSON, default=dict)
