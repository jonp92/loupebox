"""Audit log helpers.

`audit()` only adds the row to the caller's session: call it before the `commit()` that saves the
change, so the two succeed or fail together. Details must never hold secrets: list a field in
`redact` and only the fact that it changed is stored.
"""

import enum
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuditEvent, Site, User

# One-line summaries are cut here so a long name can't make the row overflow its column.
_SUMMARY_MAX = 300
SYSTEM_ACTOR = "system"  # the worker's retention sweep has no user behind it


def _plain(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return value


def snapshot(obj: object, fields: Iterable[str]) -> dict[str, Any]:
    """Current values of `fields`, taken before a change is applied."""
    return {f: _plain(getattr(obj, f)) for f in fields}


def changed(before: dict[str, Any], obj: object, redact: Iterable[str] = ()) -> dict[str, Any]:
    """Fields whose value differs from the snapshot, as {field: {"from", "to"}} (or "changed" if redacted)."""
    hidden = set(redact)
    out: dict[str, Any] = {}
    for field, old in before.items():
        new = _plain(getattr(obj, field))
        if new != old:
            out[field] = "changed" if field in hidden else {"from": old, "to": new}
    return out


def audit(
    db: Session,
    actor: User | None,
    action: str,
    summary: str,
    *,
    target_type: str,
    target_id: object,
    site: Site | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_id=actor.id if actor else None,
            actor_email=actor.email if actor else SYSTEM_ACTOR,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            site_id=site.id if site else None,
            site_name=" ".join(site.name.split())[:120] if site else None,
            summary=" ".join(summary.split())[:_SUMMARY_MAX],
            details=details or {},
        )
    )


def purge_expired(db: Session, now: datetime) -> int:
    """Delete events older than the retention period. A retention of 0 keeps everything."""
    if settings.audit_retention_days <= 0:
        return 0
    result = db.execute(
        delete(AuditEvent).where(AuditEvent.created_at < now - timedelta(days=settings.audit_retention_days))
    )
    db.commit()
    return result.rowcount
