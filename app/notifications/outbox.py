"""Writing to the outbox. Called inside the caller's transaction, never commits."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Feedback, FeedbackReply, FeedbackStatus, NotificationChannel, NotificationOutbox
from app.notifications.events import MACHINE_ONLY, FeedbackCreated, FeedbackReplied
from app.notifications.registry import get_provider


def _enqueue(db: Session, site_id, event: FeedbackCreated | FeedbackReplied) -> int:
    """One outbox row per enabled channel subscribed to the event. Returns how many."""
    channels = db.scalars(
        select(NotificationChannel).where(
            NotificationChannel.site_id == site_id, NotificationChannel.enabled.is_(True)
        )
    ).all()
    queued = 0
    for channel in channels:
        if event.type not in channel.events:
            continue
        provider = get_provider(channel.provider)
        if event.type in MACHINE_ONLY and (provider is None or provider.uses_recipients):
            continue
        db.add(
            NotificationOutbox(
                channel_id=channel.id, site_id=site_id, event_type=event.type, payload=event.model_dump()
            )
        )
        queued += 1
    return queued


def enqueue_feedback_created(db: Session, item: Feedback) -> int:
    """Queue the event for the channels subscribed to it. Returns how many.

    Quarantined spam never notifies. Add the rows before the caller's commit so the feedback and
    its notifications are stored together or not at all.
    """
    if item.status != FeedbackStatus.new:
        return 0
    return _enqueue(db, item.site_id, FeedbackCreated.from_feedback(item))


def enqueue_reply_sent(db: Session, item: Feedback, reply: FeedbackReply) -> int:
    return _enqueue(
        db,
        item.site_id,
        FeedbackReplied(feedback_id=str(item.id), reply_id=str(reply.id), length=len(reply.body)),
    )
