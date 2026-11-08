import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import ROLE_RANK, Feedback, Membership, Role, Site, User
from app.notifications.base import NotificationProvider

_bearer = HTTPBearer(auto_error=False)


def get_session_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    user_id = decode_access_token(creds.credentials)
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise unauthorized
    return user


def get_current_user(user: User = Depends(get_session_user)) -> User:
    """The signed-in user. While two-factor is required and the account has none, nothing else works:
    only the routes that use `get_session_user` (me, password, 2FA setup) stay reachable."""
    if settings.require_totp and not user.totp_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Two-factor authentication must be turned on first")
    return user


def require_configured(provider: NotificationProvider) -> None:
    if not provider.is_configured():
        raise HTTPException(status.HTTP_409_CONFLICT, f"{provider.label} is not configured on the server")


def require_superadmin(user: User = Depends(get_current_user)) -> User:
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Superadmin only")
    return user


@dataclass
class SiteAccess:
    user: User
    site: Site
    role: Role

    def has(self, role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]

    def require(self, role: Role) -> None:
        if not self.has(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {role.value} role")


def site_access(min_role: Role):
    """Dependency factory: resolves {site_id} and checks the caller holds at least `min_role`.

    Non-members get 404 so site IDs can't be probed. Superadmins act as admin everywhere.
    """

    def dependency(
        site_id: uuid.UUID = Path(),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> SiteAccess:
        site = db.get(Site, site_id)
        if site is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
        if user.is_superadmin:
            role = Role.admin
        else:
            membership = db.scalar(
                select(Membership).where(Membership.user_id == user.id, Membership.site_id == site_id)
            )
            if membership is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
            role = membership.role
        access = SiteAccess(user=user, site=site, role=role)
        access.require(min_role)
        return access

    return dependency


def visible_sites(db: Session, user: User) -> list[tuple[Site, Role]]:
    """Every site the user can see with their role there, by name: all sites for a superadmin (as admin),
    else their memberships."""
    if user.is_superadmin:
        return [(s, Role.admin) for s in db.scalars(select(Site).order_by(Site.name))]
    return [
        (site, role)
        for site, role in db.execute(
            select(Site, Membership.role)
            .join(Membership, Membership.site_id == Site.id)
            .where(Membership.user_id == user.id)
            .order_by(Site.name)
        )
    ]


def feedback_or_404(db: Session, site_id: uuid.UUID, feedback_id: uuid.UUID) -> Feedback:
    """A feedback item of this site, or 404 (an id from another site is not revealed)."""
    item = db.scalar(select(Feedback).where(Feedback.id == feedback_id, Feedback.site_id == site_id))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feedback not found")
    return item
