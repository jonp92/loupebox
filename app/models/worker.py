from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class WorkerHeartbeat(Base):
    """When each worker process (by hostname) last completed a pass; read by the System status panel."""

    __tablename__ = "worker_heartbeats"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    beat_at: Mapped[datetime] = mapped_column(default=utcnow)
