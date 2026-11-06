"""Per-site data retention, run by the worker, and the per-email erase the admin API shares.

The sweep functions commit per batch (worker jobs, like `purge_finished`): a site with a large backlog
is cleared in short transactions instead of one long lock. Each finished sweep writes one audit event
with counts only, never addresses or text. `erase_email` is the exception and leaves the commit to
its caller.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.models import Feedback, NotificationOutbox, OutboxStatus, Site

BATCH = 500
FINISHED = [OutboxStatus.sent, OutboxStatus.failed]


def _batched(db: Session, site: Site, where: list, act) -> int:
    """Run `act(ids)` on the matching feedback ids, BATCH at a time, committing after each."""
    total = 0
    while True:
        ids = db.scalars(select(Feedback.id).where(Feedback.site_id == site.id, *where).limit(BATCH)).all()
        if not ids:
            return total
        act(ids)
        db.commit()
        total += len(ids)


def delete_older_than(db: Session, site: Site, cutoff: datetime) -> int:
    return _batched(
        db,
        site,
        [Feedback.created_at < cutoff],
        lambda ids: db.execute(delete(Feedback).where(Feedback.id.in_(ids))),
    )


def strip_email_older_than(db: Session, site: Site, cutoff: datetime) -> int:
    """Null the address and the dedupe hash derived from it (the hash is only used for minutes)."""
    return _batched(
        db,
        site,
        [Feedback.created_at < cutoff, Feedback.email.is_not(None)],
        lambda ids: db.execute(
            update(Feedback).where(Feedback.id.in_(ids)).values(email=None, content_hash="")
        ),
    )


def scrub_outbox(db: Session, site: Site, cutoff: datetime) -> int:
    """The outbox keeps a copy of name, email and excerpt for each notification: finished rows older
    than the site's shortest retention go with the feedback they describe."""
    result = db.execute(
        delete(NotificationOutbox).where(
            NotificationOutbox.site_id == site.id,
            NotificationOutbox.status.in_(FINISHED),
            NotificationOutbox.created_at < cutoff,
        )
    )
    db.commit()
    return result.rowcount


def sweep_site(db: Session, site: Site, now: datetime) -> dict[str, int]:
    delete_days, strip_days = site.retention_delete_days, site.retention_strip_email_days
    counts = {"deleted": 0, "emails_stripped": 0, "notifications": 0}
    if delete_days:
        counts["deleted"] = delete_older_than(db, site, now - timedelta(days=delete_days))
    if strip_days:
        counts["emails_stripped"] = strip_email_older_than(db, site, now - timedelta(days=strip_days))
    if delete_days or strip_days:
        shortest = min(d for d in (delete_days, strip_days) if d)
        counts["notifications"] = scrub_outbox(db, site, now - timedelta(days=shortest))
    if counts["deleted"] or counts["emails_stripped"]:
        audit(
            db,
            None,
            "retention.sweep",
            f"Retention removed {counts['deleted']} items and {counts['emails_stripped']} addresses "
            f"from {site.name}",
            target_type="site",
            target_id=site.id,
            site=site,
            details=counts,
        )
        db.commit()
    return counts


def sweep(db: Session, now: datetime) -> int:
    """Apply every site's retention settings. Returns how many items were deleted or stripped."""
    sites = db.scalars(
        select(Site).where(
            Site.retention_delete_days.is_not(None) | Site.retention_strip_email_days.is_not(None)
        )
    ).all()
    changed = 0
    for site in sites:
        counts = sweep_site(db, site, now)
        changed += counts["deleted"] + counts["emails_stripped"]
    return changed


def from_email(site_id: uuid.UUID, email: str) -> list:
    """Filter for the items a person submitted: the address as typed, case-insensitively."""
    return [Feedback.site_id == site_id, func.lower(Feedback.email) == email.strip().lower()]


def erase_email(db: Session, site: Site, email: str) -> int:
    """Delete every item from this address (any status; replies, notes and tags go with it) and the
    outbox copies of it, queued or finished. Unlike the sweep this does not commit: the admin
    endpoint audits and commits, so the erase and its audit event stand or fall together."""
    deleted = db.execute(delete(Feedback).where(*from_email(site.id, email))).rowcount
    db.execute(
        delete(NotificationOutbox).where(
            NotificationOutbox.site_id == site.id,
            NotificationOutbox.event_type == "feedback.created",
            func.lower(NotificationOutbox.payload["email"].as_string()) == email.strip().lower(),
        )
    )
    return deleted
