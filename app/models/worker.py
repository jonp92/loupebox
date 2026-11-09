from datetime import datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class WorkerHeartbeat(Base):
    """When each worker process (by hostname) last completed a pass; read by the System status panel."""

    __tablename__ = "worker_heartbeats"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    beat_at: Mapped[datetime] = mapped_column(default=utcnow)


class InboundStatus(Base):
    """How the last attempt to read each inbound source went, written by the worker for System status.

    The error is a short class name and message from the mail library, never mail text or addresses.
    """

    __tablename__ = "inbound_status"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(default=None)
    last_error_at: Mapped[datetime | None] = mapped_column(default=None)
    last_error: Mapped[str | None] = mapped_column(String(200), default=None)
    last_stored_at: Mapped[datetime | None] = mapped_column(default=None)
    # What each read did with the mail it found, in hourly buckets for the last 24 hours:
    # {"2026-11-08T18": {"stored": 1, "unmatched": 2}}. Small, and a rolling window without one row per mail.
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
