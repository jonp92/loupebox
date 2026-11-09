"""Instance health for the System status panel, and the worker's heartbeat."""

import re
import socket
from collections import Counter
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import RedisLimiter, limiter
from app.inbound.base import Outcome, PollingSource
from app.inbound.registry import all_sources, load_sources
from app.models import (
    InboundStatus,
    NotificationChannel,
    NotificationOutbox,
    OutboxStatus,
    Site,
    WorkerHeartbeat,
)
from app.models.user import utcnow
from app.notifications.system_mail import mail_provider

HEARTBEAT_EVERY = 30  # seconds between beats from one worker
WORKER_STALE = timedelta(minutes=3)  # a pass can be slow while a provider times out
HEARTBEAT_KEEP = timedelta(days=1)  # rows from hostnames that no longer exist
FAILURE_WINDOW = timedelta(hours=24)
INBOUND_STALE_POLLS = 3  # a source that has not been read for this many poll intervals is stale
INBOUND_STALE_MIN = timedelta(minutes=3)
UNMATCHED_WARN = 3  # this many unmatched mails in a day with nothing stored is worth a look
COUNT_WINDOW = timedelta(hours=24)
COUNTED = ("stored", "unmatched", "bounced", "ignored")  # duplicates carry no news

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


class InboundHealth(BaseModel):
    source: str
    label: str
    status: Status
    last_ok_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None  # shortened; never mail text
    last_stored_at: datetime | None  # when a customer answer was last added to a conversation
    counts: dict[str, int]  # what happened to the mail found in the last 24 hours, by outcome


class ChecklistItem(BaseModel):
    id: Literal["mail", "public_url", "worker", "site", "channel"]
    done: bool


class Health(BaseModel):
    database: Status
    worker: WorkerHealth
    outbox: OutboxHealth
    redis: Status | None  # None: no REDIS_URL, limits are per process by design
    inbound: list[InboundHealth]  # one per configured polling source; empty while inbound email is off
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


def _bucket(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H")


def record_poll(
    db: Session,
    source: str,
    now: datetime,
    error: str | None = None,
    outcomes: Counter[Outcome] | None = None,
) -> None:
    """Note how the worker's last read of `source` went. Called by the worker, which owns its own commit."""
    row = db.get(InboundStatus, source) or InboundStatus(source=source, counts={})
    if error is not None:
        row.last_error_at, row.last_error = now, safe_error(error)
    else:
        row.last_ok_at = now
        found = {o.value: n for o, n in (outcomes or Counter()).items() if o.value in COUNTED and n}
        keep = _bucket(now - COUNT_WINDOW)
        buckets = {k: v for k, v in (row.counts or {}).items() if k > keep}  # hour keys sort as time
        if found:
            here = dict(buckets.get(_bucket(now), {}))
            for name, n in found.items():
                here[name] = here.get(name, 0) + n
            buckets[_bucket(now)] = here
        row.counts = buckets  # a new object, so the JSON column notices the change
        if found.get("stored"):
            row.last_stored_at = now
    db.add(row)
    db.commit()


def _totals(counts: dict | None, now: datetime) -> dict[str, int]:
    keep = _bucket(now - COUNT_WINDOW)
    totals = dict.fromkeys(COUNTED, 0)
    for hour, found in (counts or {}).items():
        if hour > keep:
            for name, n in found.items():
                totals[name] = totals.get(name, 0) + n
    return {name: n for name, n in totals.items() if n}


def inbound_health(db: Session, now: datetime) -> list[InboundHealth]:
    """Error: last read failed. Warn: not read lately, or unmatched mail piling up with nothing stored."""
    load_sources()
    stale = max(INBOUND_STALE_MIN, timedelta(seconds=INBOUND_STALE_POLLS * settings.imap_poll_seconds))
    out = []
    for source in all_sources():
        if not (isinstance(source, PollingSource) and source.is_configured()):
            continue
        row = db.get(InboundStatus, source.key)
        ok_at = row.last_ok_at if row else None
        error_at = row.last_error_at if row else None
        failing = error_at is not None and (ok_at is None or error_at > ok_at)
        counts = _totals(row.counts if row else None, now)
        piling_up = counts.get("unmatched", 0) >= UNMATCHED_WARN and not counts.get("stored")
        fresh = bool(ok_at) and ok_at >= now - stale and not piling_up
        status: Status = "error" if failing else "ok" if fresh else "warn"
        out.append(
            InboundHealth(
                source=source.key,
                label=source.label,
                status=status,
                last_ok_at=ok_at,
                last_error_at=error_at,
                last_error=row.last_error if row and failing else None,
                last_stored_at=row.last_stored_at if row else None,
                counts=counts,
            )
        )
    return out


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
        database="ok",
        worker=worker,
        outbox=outbox,
        redis=redis,
        inbound=inbound_health(db, now),
        checklist=checklist(db, bool(live)),
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
