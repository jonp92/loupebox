"""Attachment files outlive their database rows unless someone removes them, so everything that deletes
feedback follows one pattern: collect the keys (`keys_for`) before the delete, commit, then `delete_files`.
`sweep_orphans` is the safety net for a crash between those steps and for writes whose commit failed."""

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Feedback, FeedbackAttachment
from app.storage.registry import get_storage

log = logging.getLogger("loupebox.attachments")
ORPHAN_GRACE = timedelta(hours=1)  # a file this young may belong to a submission still being committed
CHUNK = 500


def keys_for(db: Session, *feedback_where) -> list[str]:
    """Storage keys of the attachments of the feedback items matching the conditions."""
    return list(
        db.scalars(
            select(FeedbackAttachment.storage_key)
            .join(Feedback, Feedback.id == FeedbackAttachment.feedback_id)
            .where(*feedback_where)
        )
    )


def delete_files(keys: Iterable[str]) -> None:
    """Remove files after the commit that dropped their rows. A failure is logged and left to the sweep:
    the data is already gone from the database, so the caller has nothing to undo."""
    keys = list(keys)
    if not keys:
        return
    try:
        get_storage().delete(keys)
    except Exception:
        log.exception("could not delete %s attachment files; the orphan sweep will retry", len(keys))


def sweep_orphans(db: Session, now: datetime) -> int:
    """Delete stored files that no row refers to (and are older than the grace period). Returns how many."""
    storage = get_storage()
    removed = 0

    def drop(chunk: list[str]) -> int:
        known = set(
            db.scalars(
                select(FeedbackAttachment.storage_key).where(FeedbackAttachment.storage_key.in_(chunk))
            )
        )
        orphans = [k for k in chunk if k not in known]
        storage.delete(orphans)
        return len(orphans)

    chunk: list[str] = []
    for key, modified in storage.entries():
        if modified < now - ORPHAN_GRACE:
            chunk.append(key)
        if len(chunk) >= CHUNK:
            removed += drop(chunk)
            chunk = []
    return removed + (drop(chunk) if chunk else 0)
