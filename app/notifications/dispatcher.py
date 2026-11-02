"""Drains the outbox: claim due rows, send through the channel's provider, record the outcome.

Hourly cap: a channel may send `notify_hourly_cap` emails per rolling hour. Rows past that are
`held`; once the oldest has waited `notify_summary_delay_minutes`, all of a channel's held rows go out
as one summary email.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import NotificationChannel, NotificationOutbox, OutboxStatus, Site
from app.models.user import utcnow
from app.notifications.base import NotificationProvider, SendResult
from app.notifications.messages import build_message, build_summary
from app.notifications.recipients import resolve_recipients
from app.notifications.registry import get_provider

log = logging.getLogger("ganymede.notifications")

# Wait before attempt 2, 3, ...; after the last delay is used up the next failure is final.
RETRY_DELAYS = [
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(hours=6),
]
# A claimed row that never reports back (worker crash) becomes due again after this long.
LEASE = timedelta(minutes=5)
CAP_WINDOW = timedelta(hours=1)
ERROR_MAX = 500


@dataclass
class Target:
    channel: NotificationChannel
    provider: NotificationProvider
    config: BaseModel
    site: Site
    recipients: list[str]


def claim_due(db: Session, now: datetime, limit: int) -> list[NotificationOutbox]:
    """Lease up to `limit` due rows. SKIP LOCKED lets several workers run side by side on Postgres."""
    rows = db.scalars(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.status.in_([OutboxStatus.pending, OutboxStatus.sending]),
            NotificationOutbox.next_attempt_at <= now,
        )
        .order_by(NotificationOutbox.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        row.status = OutboxStatus.sending
        row.attempts += 1
        row.next_attempt_at = now + LEASE
    db.commit()
    return list(rows)


def _prepare(db: Session, channel_id, site_id) -> Target | SendResult:
    """Everything needed to send for a channel, or the permanent failure that rules it out."""
    channel = db.get(NotificationChannel, channel_id) if channel_id else None
    if channel is None or not channel.enabled:
        return SendResult.failed("channel deleted or disabled")
    provider = get_provider(channel.provider)
    if provider is None:
        return SendResult.failed(f"unknown provider {channel.provider!r}")
    if not provider.is_configured():
        return SendResult.failed(f"provider {channel.provider!r} is not configured on the server")
    try:
        config = provider.ConfigModel.model_validate(channel.config)
    except ValidationError:
        return SendResult.failed("invalid channel config")
    site = db.get(Site, site_id)
    if site is None:
        return SendResult.failed("site deleted")
    recipients = resolve_recipients(db, channel)
    if not recipients:
        return SendResult.failed("no recipients")
    return Target(channel, provider, config, site, recipients)


def _cap_reached(db: Session, channel: NotificationChannel, now: datetime) -> bool:
    sends = db.scalar(
        select(func.count())
        .select_from(NotificationOutbox)
        .where(
            NotificationOutbox.channel_id == channel.id,
            NotificationOutbox.status == OutboxStatus.sent,
            NotificationOutbox.sent_at > now - CAP_WINDOW,
            # A summary is one email however many rows it covered: count only its anchor row.
            or_(
                NotificationOutbox.summary_id.is_(None),
                NotificationOutbox.summary_id == NotificationOutbox.id,
            ),
        )
    )
    return (sends or 0) >= settings.notify_hourly_cap


def _call(target: Target, message) -> SendResult:
    try:
        return target.provider.send(message, target.config)
    except Exception as exc:  # a buggy provider must not kill the worker
        log.exception("provider %s raised", target.provider.key)
        return SendResult.retry(f"{type(exc).__name__}: {exc}")


def _record(
    row: NotificationOutbox, result: SendResult, now: datetime, retry_status=OutboxStatus.pending
) -> None:
    if result.status == "sent":
        row.status = OutboxStatus.sent
        row.sent_at = now
        row.provider_message_id = result.message_id
        row.last_error = None
        return
    row.last_error = (result.error or "")[:ERROR_MAX]
    if result.status == "retry" and row.attempts <= len(RETRY_DELAYS):
        row.status = retry_status
        row.next_attempt_at = now + RETRY_DELAYS[row.attempts - 1]
    else:
        row.status = OutboxStatus.failed


def _hold(db: Session, row: NotificationOutbox, now: datetime) -> None:
    """Park a row for the summary. It joins the channel's pending summary if there is one."""
    due = db.scalar(
        select(func.min(NotificationOutbox.next_attempt_at)).where(
            NotificationOutbox.channel_id == row.channel_id,
            NotificationOutbox.status == OutboxStatus.held,
        )
    )
    row.status = OutboxStatus.held
    row.attempts = 0  # never tried; the summary counts its own attempts
    row.next_attempt_at = due or now + timedelta(minutes=settings.notify_summary_delay_minutes)


def _send_row(db: Session, row: NotificationOutbox, now: datetime) -> None:
    target = _prepare(db, row.channel_id, row.site_id)
    if isinstance(target, SendResult):
        _record(row, target, now)
    elif _cap_reached(db, target.channel, now):
        _hold(db, row, now)
    else:
        _record(row, _call(target, build_message(row, target.site, target.recipients)), utcnow())


def process_summaries(db: Session, now: datetime) -> int:
    """Send one summary per channel whose held rows are due. Returns the number of rows covered."""
    channel_ids = db.scalars(
        select(NotificationOutbox.channel_id)
        .where(NotificationOutbox.status == OutboxStatus.held, NotificationOutbox.next_attempt_at <= now)
        .distinct()
    ).all()
    handled = 0
    for channel_id in channel_ids:
        # The row locks stay held through the send, so a second worker skips this channel.
        same_channel = (
            NotificationOutbox.channel_id == channel_id
            if channel_id
            else NotificationOutbox.channel_id.is_(None)
        )
        rows = db.scalars(
            select(NotificationOutbox)
            .where(NotificationOutbox.status == OutboxStatus.held, same_channel)
            .order_by(NotificationOutbox.created_at)
            .with_for_update(skip_locked=True)
        ).all()
        if not rows:
            continue
        site_id = rows[0].site_id
        target = _prepare(db, channel_id, site_id)
        result = (
            target
            if isinstance(target, SendResult)
            else _call(target, build_summary(list(rows), target.site, target.recipients))
        )
        for row in rows:
            row.attempts += 1
            _record(row, result, utcnow(), retry_status=OutboxStatus.held)
            if result.status == "sent":
                row.summary_id = rows[0].id
        db.commit()
        handled += len(rows)
    return handled


def process_due(db: Session, *, limit: int = 20) -> int:
    """One worker pass. Returns the number of rows handled."""
    now = utcnow()
    rows = claim_due(db, now, limit)
    for row in rows:
        _send_row(db, row, now)
        db.commit()
    return len(rows) + process_summaries(db, utcnow())
