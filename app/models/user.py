import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    last_name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    # Image bytes are deferred so ordinary user queries never load them; the avatar route does.
    avatar_data: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, default=None))
    avatar_type: Mapped[str | None] = mapped_column(String(16), default=None)
    avatar_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # TOTP. The secret is encrypted (app/core/totp.py). It is set at setup but only counts once
    # `totp_enabled_at` is set by confirming a code. `totp_last_step` stops a code being used twice.
    totp_secret: Mapped[str | None] = mapped_column(String(255), default=None)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, default=None)

    @property
    def totp_enabled(self) -> bool:
        return self.totp_enabled_at is not None

    @property
    def avatar_url(self) -> str | None:
        """Relative URL; the version query busts caches when the image changes."""
        if self.avatar_updated_at is None:
            return None
        ts = self.avatar_updated_at
        ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
        return f"{settings.api_prefix}/avatars/{self.id}?v={int(ts.timestamp())}"

    memberships: Mapped[list["Membership"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecoveryCode(Base):
    """One-time code that stands in for an authenticator code. Only the hash is stored."""

    __tablename__ = "recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
