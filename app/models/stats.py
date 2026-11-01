import enum
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StatKind(str, enum.Enum):
    """Why a public submission was dropped. Quarantined spam isn't here: it's stored as feedback
    with status=spam and counted from there."""

    honeypot = "honeypot"  # hidden field filled in
    duplicate = "duplicate"  # identical message resubmitted within the dedupe window
    origin_denied = "origin_denied"  # valid key, but Origin missing or not allowed
    rate_limited = "rate_limited"  # per-key rate limit hit
    daily_limit = "daily_limit"  # site's daily quota reached


class SiteStat(Base):
    """Daily (UTC) counter of dropped submissions per site and reason."""

    __tablename__ = "site_stats"

    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
