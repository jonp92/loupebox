import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.site import Role
from app.models.user import utcnow

_JSON = JSON().with_variant(JSONB(), "postgresql")


class OutboxStatus(str, enum.Enum):
    pending = "pending"
    sending = "sending"  # claimed by a worker; next_attempt_at is the lease expiry
    sent = "sent"
    failed = "failed"
    held = "held"  # over the hourly cap, waiting for the summary


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(_JSON, default=dict)  # provider settings, never secrets
    events: Mapped[list[str]] = mapped_column(JSON, default=list)
    min_role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=16), default=Role.admin)
    filters: Mapped[dict] = mapped_column(_JSON, default=dict)  # app.notifications.filters; {} = everything
    extra_recipients: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Signing secret for providers that sign (webhooks), encrypted with app.core.crypto.
    secret: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    @property
    def has_secret(self) -> bool:
        return self.secret is not None


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (Index("ix_outbox_status_next", "status", "next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Set null on channel delete so the delivery log survives.
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="SET NULL"), index=True, default=None
    )
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict] = mapped_column(_JSON, default=dict)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, native_enum=False, length=16), default=OutboxStatus.pending
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    # Set on rows covered by a summary email: the id of the row that anchors it. A summary counts
    # as one send against the hourly cap however many rows it covers.
    summary_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(default=None)
