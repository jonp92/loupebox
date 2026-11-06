import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, ForeignKey, Index, SmallInteger, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.db.base import Base
from app.models.user import User, utcnow


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
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Who is dealing with it: always a member of the site when set, cleared when they leave it.
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )

    tag_rows: Mapped[list["FeedbackTag"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="FeedbackTag.tag"
    )

    @property
    def tags(self) -> list[str]:
        return [t.tag for t in self.tag_rows]


class FeedbackTag(Base):
    """A per-site free-text label; one row per (item, tag)."""

    __tablename__ = "feedback_tags"

    feedback_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)


class FeedbackNote(Base):
    """An internal note for the team. Never shown to the submitter."""

    __tablename__ = "feedback_notes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feedback.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FeedbackReply(Base):
    """One message in the conversation with the submitter. The recipient address stays on the feedback item.

    `direction` and `source` are there for inbound email: today every row is an outbound reply written in
    the UI. `message_id` is what the mail provider returned, kept to match bounces and replies to a thread.
    """

    __tablename__ = "feedback_replies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feedback.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    direction: Mapped[str] = mapped_column(String(8), default="outbound")  # outbound | inbound
    source: Mapped[str] = mapped_column(String(8), default="ui")  # ui | email
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8))  # sent | failed
    error: Mapped[str | None] = mapped_column(String(300), default=None)
    retryable: Mapped[bool] = mapped_column(default=False)  # a failed send worth trying again (temporary)
    message_id: Mapped[str | None] = mapped_column(String(128), default=None)
    in_reply_to: Mapped[str | None] = mapped_column(String(128), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# Counted in the same query as the item, so lists can show "3 notes" without opening each one.
Feedback.note_count = column_property(
    select(func.count(FeedbackNote.id))
    .where(FeedbackNote.feedback_id == Feedback.id)
    .correlate_except(FeedbackNote)
    .scalar_subquery(),
    deferred=False,
)


Feedback.reply_count = column_property(
    select(func.count(FeedbackReply.id))
    .where(FeedbackReply.feedback_id == Feedback.id, FeedbackReply.status == "sent")
    .correlate_except(FeedbackReply)
    .scalar_subquery(),
    deferred=False,
)


def user_name():
    """SQL for how a person is shown: their name, or their email when they have none."""
    return func.coalesce(func.nullif(func.trim(User.first_name + " " + User.last_name), ""), User.email)


Feedback.assignee_name = column_property(
    select(user_name()).where(User.id == Feedback.assignee_id).correlate_except(User).scalar_subquery(),
    deferred=False,
)
