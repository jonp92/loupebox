"""Attachment files outlive their database rows unless someone removes them, so everything that deletes
feedback follows one pattern: collect the files (`keys_for`) before the delete, commit, then `delete_files`.
`sweep_orphans` is the safety net for a crash between those steps and for writes whose commit failed.

Each attachment remembers which storage backend holds its file, so changing the setting only affects new
files. `move_images` copies the old ones over when the operator wants everything in one place.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Feedback, FeedbackAttachment
from app.storage.registry import get_storage

log = logging.getLogger("loupebox.attachments")
ORPHAN_GRACE = timedelta(hours=1)  # a file this young may belong to a submission still being committed
CHUNK = 500
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# What this app writes: `<site id>/<attachment id>`, plus the temporary and probe files. The sweep leaves
# anything else alone, so a bucket shared with other things is safe.
_OURS = re.compile(rf"^{_UUID}/{_UUID}$|^(_tmp|_check)/[0-9a-f]{{32}}$")


class StoredFile(NamedTuple):
    storage: str  # the backend's key, e.g. "local" or "s3"
    key: str


def keys_for(db: Session, *feedback_where) -> list[StoredFile]:
    """The files of the attachments of the feedback items matching the conditions."""
    rows = db.execute(
        select(FeedbackAttachment.storage, FeedbackAttachment.storage_key)
        .join(Feedback, Feedback.id == FeedbackAttachment.feedback_id)
        .where(*feedback_where)
    )
    return [StoredFile(storage, key) for storage, key in rows]


def delete_files(files: Iterable[StoredFile]) -> None:
    """Remove files after the commit that dropped their rows. A failure is logged and left to the sweep:
    the data is already gone from the database, so the caller has nothing to undo."""
    by_storage: dict[str, list[str]] = defaultdict(list)
    for storage, key in files:
        by_storage[storage].append(key)
    for storage, keys in by_storage.items():
        try:
            get_storage(storage).delete(keys)
        except Exception:
            log.exception(
                "could not delete %s attachment files from %s; the orphan sweep will retry",
                len(keys),
                storage,
            )


def storage_counts(db: Session) -> dict[str, int]:
    """How many attachment files each storage backend holds."""
    rows = db.execute(select(FeedbackAttachment.storage, func.count()).group_by(FeedbackAttachment.storage))
    return {storage: count for storage, count in rows}


def sweep_orphans(db: Session, now: datetime) -> int:
    """Delete stored files that no row refers to (and are older than the grace period), in every storage that
    holds attachments and in the current one. Returns how many."""
    names = {*storage_counts(db), settings.storage_backend}
    removed = 0
    for name in sorted(names):
        storage = get_storage(name)
        if not storage.is_configured():
            log.warning("orphan sweep skipped %s: it is not set up", name)
            continue
        try:
            removed += _sweep(db, name, now)
        except Exception:
            log.exception("orphan sweep of %s failed", name)
    return removed


def _sweep(db: Session, name: str, now: datetime) -> int:
    storage = get_storage(name)
    removed = 0

    def drop(chunk: list[str]) -> int:
        known = set(
            db.scalars(
                select(FeedbackAttachment.storage_key).where(
                    FeedbackAttachment.storage == name, FeedbackAttachment.storage_key.in_(chunk)
                )
            )
        )
        orphans = [k for k in chunk if k not in known]
        storage.delete(orphans)
        return len(orphans)

    chunk: list[str] = []
    for key, modified in storage.entries():
        if _OURS.match(key) and modified < now - ORPHAN_GRACE:
            chunk.append(key)
        if len(chunk) >= CHUNK:
            removed += drop(chunk)
            chunk = []
    return removed + (drop(chunk) if chunk else 0)


@dataclass
class MoveOutcome:
    moved: int = 0
    missing: int = 0  # the file was already gone; the row now points at the new storage anyway
    failed: int = 0
    remaining: int = 0
    error: str = ""


def move_images(db: Session, target: str, limit: int) -> MoveOutcome:
    """Copy up to `limit` attachment files that are not in `target` over to it, then remove the old copies.
    Safe to repeat, and safe while people submit and delete feedback: the row is switched only if it still
    points at the old place, and a copy made for a row that has since been deleted is removed again."""
    result = MoveOutcome()
    destination = get_storage(target)
    rows = db.scalars(
        select(FeedbackAttachment)
        .where(FeedbackAttachment.storage != target)
        .order_by(FeedbackAttachment.created_at)
        .limit(limit)
    ).all()
    for row in rows:
        old, key, attachment_id = row.storage, row.storage_key, row.id
        copied = True
        try:
            try:
                data = get_storage(old).get(key)
                destination.put(key, data, row.content_type)
            except FileNotFoundError:
                copied = False  # nothing to copy, and nothing lost by moving the row
                result.missing += 1
            switched = db.execute(
                update(FeedbackAttachment)
                .where(FeedbackAttachment.id == attachment_id, FeedbackAttachment.storage == old)
                .values(storage=target)
            ).rowcount
            db.commit()
        except Exception as e:  # noqa: BLE001  (one bad file must not stop the rest; the operator sees why)
            db.rollback()
            result.failed += 1
            result.error = result.error or get_storage(target).explain(e)
            log.warning("could not move an attachment from %s to %s: %s", old, target, type(e).__name__)
            continue
        if switched:
            delete_files([StoredFile(old, key)])
            result.moved += copied
        elif db.scalar(select(FeedbackAttachment.id).where(FeedbackAttachment.id == attachment_id)) is None:
            delete_files([StoredFile(target, key)])  # deleted while we copied: do not leave the copy behind
    result.remaining = (
        db.scalar(
            select(func.count()).select_from(FeedbackAttachment).where(FeedbackAttachment.storage != target)
        )
        or 0
    )
    return result
