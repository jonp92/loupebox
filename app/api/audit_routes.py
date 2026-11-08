import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_superadmin
from app.db.session import get_db
from app.models import AuditEvent
from app.schemas.audit import AuditOut, AuditPage

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_superadmin)])


@router.get("/actions")
def list_actions(db: Session = Depends(get_db)) -> list[str]:
    """Every action recorded so far, for the filters: new audited actions show up without a list to update."""
    return list(db.scalars(select(AuditEvent.action).distinct().order_by(AuditEvent.action)))


@router.get("")
def list_audit(
    db: Session = Depends(get_db),
    group: str | None = Query(default=None, max_length=24, pattern=r"^[a-z_]+$"),
    action: str | None = Query(default=None, max_length=48),
    site_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AuditPage:
    """Newest first. `group` is the part of the action before the dot (user, site, member, ...)."""
    stmt = select(AuditEvent)
    if group:
        stmt = stmt.where(AuditEvent.action.startswith(f"{group}.", autoescape=True))
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if site_id:
        stmt = stmt.where(AuditEvent.site_id == site_id)
    if actor_id:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    if q:
        stmt = stmt.where(
            or_(
                AuditEvent.summary.icontains(q, autoescape=True),
                AuditEvent.actor_email.icontains(q, autoescape=True),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id).limit(limit).offset(offset))
    return AuditPage(items=[AuditOut.model_validate(r) for r in rows], total=total)
