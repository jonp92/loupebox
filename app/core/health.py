"""Instance health for the System status panel, and the worker's heartbeat."""

import re
import socket
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import RedisLimiter, limiter
from app.models import NotificationChannel, NotificationOutbox, OutboxStatus, Site, WorkerHeartbeat
from app.models.user import utcnow
from app.notifications.system_mail import mail_provider

HEARTBEAT_EVERY = 30  # seconds between beats from one worker
WORKER_STALE = timedelta(minutes=3)  # a pass can be slow while a provider times out
HEARTBEAT_KEEP = timedelta(days=1)  # rows from hostnames that no longer exist
FAILURE_WINDOW = timedelta(hours=24)

Status = Literal["ok", "warn", "error"]

FAILURES_SHOWN = 10
ERROR_SHOWN = 200
# Webhook URLs carry tokens in the path, query or userinfo, and library errors echo them back: keep
# only scheme and host.
_URL = re.compile(r"(https?://)(?:[^/\s@\"'<>]*@)?([^/\s\"'<>]+)[^\s\"'<>]*")


def safe_error(error: str | None) -> str:
    return _URL.sub(r"\1\2", error or "")[:ERROR_SHOWN]


class WorkerHealth(BaseModel):
    status: Status
    last_beat_at: datetime | None
    live: int  # workers that beat recently


class Failure(BaseModel):
    site: str
    channel: str | None  # None once the channel was deleted
    provider: str | None
    queued_at: datetime
    attempts: int
    error: str  # shortened, URLs reduced to their host


class OutboxHealth(BaseModel):
    status: Status
    pending: int
    held: int
    failed_24h: int
    oldest_due_seconds: int | None  # how long the longest-waiting due row has been waiting
    recent_failures: list[Failure]


class ChecklistItem(BaseModel):
    id: Literal["mail", "public_url", "worker", "site", "channel"]
    done: bool


class Health(BaseModel):
    database: Status
    worker: WorkerHealth
    outbox: OutboxHealth
    redis: Status | None  # None: no REDIS_URL, limits are per process by design
    checklist: list[ChecklistItem]


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
            NotificationOutbox.created_at >= now - FAILURE_WINDOW,
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
        recent_failures=recent_failures(db, now),
    )
    redis = None
    if isinstance(limiter, RedisLimiter):
        redis = "ok" if limiter.ping() else "warn"  # down means per-process limits, not an outage
    return Health(
        database="ok", worker=worker, outbox=outbox, redis=redis, checklist=checklist(db, bool(live))
    )


def checklist(db: Session, worker_live: bool) -> list[ChecklistItem]:
    """What a new install still needs, in the order to do it."""
    done = {
        "mail": mail_provider() is not None,
        "public_url": bool(settings.public_url),
        "worker": worker_live,
        "site": db.scalar(select(Site.id).limit(1)) is not None,
        "channel": db.scalar(select(NotificationChannel.id).where(NotificationChannel.enabled).limit(1))
        is not None,
    }
    return [ChecklistItem(id=key, done=value) for key, value in done.items()]


def recent_failures(db: Session, now: datetime) -> list[Failure]:
    """The latest failed notifications of the last 24 hours, newest first."""
    rows = db.execute(
        select(NotificationOutbox, Site.name, NotificationChannel.name, NotificationChannel.provider)
        .join(Site, Site.id == NotificationOutbox.site_id)
        .outerjoin(NotificationChannel, NotificationChannel.id == NotificationOutbox.channel_id)
        .where(
            NotificationOutbox.status == OutboxStatus.failed,
            NotificationOutbox.created_at >= now - FAILURE_WINDOW,
        )
        .order_by(NotificationOutbox.created_at.desc())
        .limit(FAILURES_SHOWN)
    )
    return [
        Failure(
            site=site,
            channel=channel,
            provider=provider,
            queued_at=row.created_at,
            attempts=row.attempts,
            error=safe_error(row.last_error),
        )
        for row, site, channel, provider in rows
    ]
