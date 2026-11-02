"""Writing to the outbox. Called inside the caller's transaction, never commits."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Feedback, FeedbackStatus, NotificationChannel, NotificationOutbox
from app.notifications.events import FeedbackCreated


def enqueue_feedback_created(db: Session, item: Feedback) -> int:
    """Queue one outbox row per enabled channel subscribed to the event. Returns how many.

    Quarantined spam never notifies. Add the rows before the caller's commit so the feedback and
    its notifications are stored together or not at all.
    """
    if item.status != FeedbackStatus.new:
        return 0
    event = FeedbackCreated.from_feedback(item)
    channels = db.scalars(
        select(NotificationChannel).where(
            NotificationChannel.site_id == item.site_id, NotificationChannel.enabled.is_(True)
        )
    ).all()
    queued = 0
    for channel in channels:
        if event.type not in channel.events:
            continue
        db.add(
            NotificationOutbox(
                channel_id=channel.id,
                site_id=item.site_id,
                event_type=event.type,
                payload=event.model_dump(),
            )
        )
        queued += 1
    return queued
