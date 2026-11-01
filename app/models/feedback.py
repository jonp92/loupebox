import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class FeedbackStatus(str, enum.Enum):
    new = "new"
    read = "read"
    archived = "archived"
    spam = "spam"


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        Index("ix_feedback_site_created", "site_id", "created_at"),
        Index("ix_feedback_site_dedupe", "site_id", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    message: Mapped[str] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    name: Mapped[str | None] = mapped_column(String(120), default=None)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    page_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    meta: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=dict)
    status: Mapped[FeedbackStatus] = mapped_column(
        Enum(FeedbackStatus, native_enum=False, length=16), default=FeedbackStatus.new
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    ip_hash: Mapped[str] = mapped_column(String(32))
    user_agent: Mapped[str | None] = mapped_column(String(256), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
