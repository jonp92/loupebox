"""Instance health for the System status panel, and the worker's heartbeat."""

import socket
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.rate_limit import RedisLimiter, limiter
from app.models import NotificationOutbox, OutboxStatus, WorkerHeartbeat
from app.models.user import utcnow

HEARTBEAT_EVERY = 30  # seconds between beats from one worker
WORKER_STALE = timedelta(minutes=3)  # a pass can be slow while a provider times out
HEARTBEAT_KEEP = timedelta(days=1)  # rows from hostnames that no longer exist

Status = Literal["ok", "warn", "error"]


class WorkerHealth(BaseModel):
    status: Status
    last_beat_at: datetime | None
    live: int  # workers that beat recently


class OutboxHealth(BaseModel):
    status: Status
    pending: int
    held: int
    failed_24h: int
    oldest_due_seconds: int | None  # how long the longest-waiting due row has been waiting


class Health(BaseModel):
    database: Status
    worker: WorkerHealth
    outbox: OutboxHealth
    redis: Status | None  # None: no REDIS_URL, limits are per process by design


def beat(db: Session, now: datetime) -> None:
    """Record that this worker is alive. Called by the worker, which owns its own commit."""
    name = socket.gethostname()
    row = db.get(WorkerHeartbeat, name)
    if row:
        row.beat_at = now
    else:
        db.add(WorkerHeartbeat(name=name, beat_at=now))
    db.commit()


def purge_heartbeats(db: Session, now: datetime) -> int:
    removed = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.beat_at < now - HEARTBEAT_KEEP).delete()
    db.commit()
    return removed


def check(db: Session, now: datetime | None = None) -> Health:
    now = now or utcnow()
    db.execute(text("SELECT 1"))  # reaching this line means the database answers

    beats = list(db.scalars(select(WorkerHeartbeat.beat_at)))
    live = sum(b >= now - WORKER_STALE for b in beats)
    worker = WorkerHealth(status="ok" if live else "error", last_beat_at=max(beats, default=None), live=live)

    by_status = select(NotificationOutbox.status, func.count()).group_by(NotificationOutbox.status)
    counts = dict(db.execute(by_status).all())
    pending = counts.get(OutboxStatus.pending, 0)
    failed = db.scalar(
        select(func.count()).where(
            NotificationOutbox.status == OutboxStatus.failed,
            NotificationOutbox.created_at >= now - timedelta(hours=24),
        )
    )
    oldest = db.scalar(
        select(func.min(NotificationOutbox.next_attempt_at)).where(
            NotificationOutbox.status == OutboxStatus.pending, NotificationOutbox.next_attempt_at <= now
        )
    )
    waited = int((now - oldest).total_seconds()) if oldest else None
    stuck = bool(pending) and not live
    outbox = OutboxHealth(
        status="error" if stuck else "warn" if failed else "ok",
        pending=pending,
        held=counts.get(OutboxStatus.held, 0),
        failed_24h=failed,
        oldest_due_seconds=waited,
    )
    redis = None
    if isinstance(limiter, RedisLimiter):
        redis = "ok" if limiter.ping() else "warn"  # down means per-process limits, not an outage
    return Health(database="ok", worker=worker, outbox=outbox, redis=redis)
