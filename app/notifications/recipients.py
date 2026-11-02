from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ROLE_RANK, Membership, NotificationChannel, User


def resolve_recipients(db: Session, channel: NotificationChannel) -> list[str]:
    """Active members at or above the channel's minimum role, then the extra addresses.

    Resolved at send time so membership changes apply to rows already queued. Deduplicated
    case-insensitively and capped, so one channel cannot fan out into a mail bomb.
    """
    min_rank = ROLE_RANK[channel.min_role]
    members = db.execute(
        select(User.email, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.site_id == channel.site_id, User.is_active.is_(True))
        .order_by(User.email)
    ).all()
    candidates = [email for email, role in members if ROLE_RANK[role] >= min_rank]
    candidates += channel.extra_recipients

    seen: set[str] = set()
    result: list[str] = []
    for address in candidates:
        key = address.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(address.strip())
    return result[: settings.notify_max_recipients]
