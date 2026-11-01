import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.stats import SiteStat, StatKind


def record(db: Session, site_id: uuid.UUID, kind: StatKind) -> None:
    """Increment today's counter for (site, kind) and commit.

    Portable upsert: UPDATE first; if no row yet, INSERT; if another request inserted it in
    between (IntegrityError), UPDATE again. Callers use this right before returning or raising,
    so nothing else is pending in the session.
    """
    day = datetime.now(UTC).date()
    bump = (
        update(SiteStat)
        .where(SiteStat.site_id == site_id, SiteStat.day == day, SiteStat.kind == kind.value)
        .values(count=SiteStat.count + 1)
    )
    if db.execute(bump).rowcount == 0:
        db.add(SiteStat(site_id=site_id, day=day, kind=kind.value, count=1))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            db.execute(bump)
    db.commit()
