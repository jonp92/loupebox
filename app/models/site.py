import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import User, utcnow


class Role(str, enum.Enum):
    viewer = "viewer"  # read feedback
    editor = "editor"  # + triage (change status)
    admin = "admin"  # + delete feedback, manage site settings, keys and members


ROLE_RANK = {Role.viewer: 1, Role.editor: 2, Role.admin: 3}


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    public_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    allowed_origins: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_limit: Mapped[int] = mapped_column(Integer)
    # Public-ingest challenge: "off" or the key of a registered app.challenges verifier.
    challenge_mode: Mapped[str] = mapped_column(String(24), default="off", server_default="off")
    challenge_config: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "site_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=16))

    user: Mapped[User] = relationship(back_populates="memberships")
    site: Mapped[Site] = relationship(back_populates="memberships")
