"""The one path every inbound source feeds: match a message to a feedback item and store it.

Nothing here logs or audits message text or addresses. The caller owns the transaction (this adds rows and
never commits), like every helper that runs inside a request or a worker pass.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.events import publish
from app.inbound.base import InboundMessage, Outcome
from app.inbound.mime import normalize_id
from app.inbound.text import strip_quoted
from app.inbound.token import feedback_id_from_address
from app.models import Feedback, FeedbackReply, FeedbackStatus
from app.notifications.outbox import enqueue_customer_reply

BODY_MAX = 5000  # the same cap as a reply written in the UI
ERROR_MAX = 300
ID_MAX = 128


def _forms(message_id: str | None) -> list[str]:
    """How a stored Message-ID might be spelled: providers keep it with or without the angle brackets."""
    value = normalize_id(message_id)
    return [value, f"<{value}>"] if value else []


def _fit(message_id: str | None) -> str | None:
    """The column holds 128 characters; a longer id is dropped (the mail is stored, just not deduped)."""
    value = normalize_id(message_id)
    return value if value and len(value) <= ID_MAX else None


def _reply_with_id(db: Session, ids: list[str], direction: str | None = None) -> FeedbackReply | None:
    forms = [f for i in ids for f in _forms(i)]
    if not forms:
        return None
    query = select(FeedbackReply).where(FeedbackReply.message_id.in_(forms))
    if direction:
        query = query.where(FeedbackReply.direction == direction)
    return db.scalar(query.limit(1))


def _match(db: Session, msg: InboundMessage) -> Feedback | None:
    """The address token first (it is ours alone), then the threading headers."""
    for address in msg.recipients:
        feedback_id = feedback_id_from_address(address)
        if feedback_id is not None and (item := db.get(Feedback, feedback_id)):
            return item
    related = _reply_with_id(db, [msg.in_reply_to or "", *msg.references])
    return db.get(Feedback, related.feedback_id) if related else None


def _bounce(db: Session, msg: InboundMessage) -> Outcome:
    reply = _reply_with_id(db, [msg.bounced_message_id or ""], "outbound")
    if reply is None:
        return Outcome.unmatched
    reply.status = "failed"
    reply.retryable = False
    reply.error = (f"Bounced ({msg.bounce_code})" if msg.bounce_code else "Bounced")[:ERROR_MAX]
    if item := db.get(Feedback, reply.feedback_id):
        publish(db, "thread", item.site_id, item.id)
    return Outcome.bounced


def ingest(db: Session, msg: InboundMessage) -> Outcome:
    if msg.kind == "auto":
        return Outcome.ignored
    if msg.kind == "bounce":
        return _bounce(db, msg)
    item = _match(db, msg)
    # The token routes the mail but is not a login: only the person who wrote the feedback can answer it.
    if item is None or not item.email or item.email.strip().lower() != msg.sender.strip().lower():
        return Outcome.unmatched
    if item.status == FeedbackStatus.spam:
        return Outcome.ignored
    body = strip_quoted(msg.text)[:BODY_MAX]
    if not body:
        return Outcome.ignored
    reply = FeedbackReply(
        id=uuid.uuid4(),
        feedback_id=item.id,
        direction="inbound",
        source="email",
        body=body,
        status="sent",
        message_id=_fit(msg.message_id),
        in_reply_to=_fit(msg.in_reply_to),
    )
    try:
        with db.begin_nested():  # a unique index on inbound Message-IDs turns a race into a duplicate
            db.add(reply)
            db.flush()
    except IntegrityError:
        return Outcome.duplicate
    if item.status != FeedbackStatus.new:
        item.status = FeedbackStatus.new  # someone is waiting on us again: back to unread
    enqueue_customer_reply(db, item, reply)
    publish(db, "thread", item.site_id, item.id)
    publish(db, "feedback", item.site_id, item.id)  # the status, reply count and list order changed too
    return Outcome.stored
