from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UsedChallenge(Base):
    """Replay guard: a challenge id lands here when its proof is accepted, until the challenge expires."""

    __tablename__ = "used_challenges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
