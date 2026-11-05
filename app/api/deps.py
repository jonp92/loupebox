import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import ROLE_RANK, Membership, Role, Site, User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
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


def require_superadmin(user: User = Depends(get_current_user)) -> User:
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Superadmin only")
    return user


@dataclass
class SiteAccess:
    user: User
    site: Site
    role: Role


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
        if ROLE_RANK[role] < ROLE_RANK[min_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {min_role.value} role")
        return SiteAccess(user=user, site=site, role=role)

    return dependency
