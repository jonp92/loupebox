import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, get_current_user, require_superadmin, site_access
from app.core.config import settings
from app.core.origins import public_origins
from app.core.security import new_public_key
from app.db.session import get_db
from app.models import Membership, Role, Site, User
from app.schemas.site import (
    MemberOut,
    MemberUpsert,
    SiteCreate,
    SiteOut,
    SiteUpdate,
    UserSuggestion,
)

router = APIRouter(prefix="/sites", tags=["sites"])


def _profile(u: User) -> dict:
    return {"email": u.email, "first_name": u.first_name, "last_name": u.last_name, "avatar_url": u.avatar_url}


def _out(site: Site, role: Role | None) -> SiteOut:
    out = SiteOut.model_validate(site)
    out.my_role = role
    return out


@router.get("")
def list_sites(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SiteOut]:
    if user.is_superadmin:
        return [_out(s, Role.admin) for s in db.scalars(select(Site).order_by(Site.name))]
    rows = db.execute(
        select(Site, Membership.role)
        .join(Membership, Membership.site_id == Site.id)
        .where(Membership.user_id == user.id)
        .order_by(Site.name)
    )
    return [_out(site, role) for site, role in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_site(
    body: SiteCreate, _: User = Depends(require_superadmin), db: Session = Depends(get_db)
) -> SiteOut:
    site = Site(
        name=body.name,
        public_key=new_public_key(),
        allowed_origins=body.allowed_origins,
        daily_limit=body.daily_limit or settings.default_site_daily_limit,
    )
    db.add(site)
    db.commit()
    public_origins.invalidate()
    return _out(site, Role.admin)


@router.get("/{site_id}")
def get_site(access: SiteAccess = Depends(site_access(Role.viewer))) -> SiteOut:
    return _out(access.site, access.role)


@router.patch("/{site_id}")
def update_site(
    body: SiteUpdate,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> SiteOut:
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        setattr(access.site, field, value)
    db.commit()
    public_origins.invalidate()
    return _out(access.site, access.role)


@router.post("/{site_id}/rotate-key")
def rotate_key(
    access: SiteAccess = Depends(site_access(Role.admin)), db: Session = Depends(get_db)
) -> SiteOut:
    """Issue a new public key; the old one stops working immediately."""
    access.site.public_key = new_public_key()
    db.commit()
    return _out(access.site, access.role)


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_site(
    site_id: uuid.UUID, _: User = Depends(require_superadmin), db: Session = Depends(get_db)
) -> None:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    db.delete(site)
    db.commit()
    public_origins.invalidate()


@router.get("/{site_id}/members")
def list_members(
    access: SiteAccess = Depends(site_access(Role.admin)), db: Session = Depends(get_db)
) -> list[MemberOut]:
    rows = db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.site_id == access.site.id)
        .order_by(User.email)
    )
    return [MemberOut(user_id=u.id, role=role, **_profile(u)) for u, role in rows]


@router.get("/{site_id}/user-search")
def search_users(
    q: str = Query(min_length=2, max_length=100),
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> list[UserSuggestion]:
    """Email autocomplete for the add-member picker. Only active users who aren't already members."""
    members = select(Membership.user_id).where(Membership.site_id == access.site.id)
    rows = db.scalars(
        select(User)
        .where(
            or_(
                User.email.icontains(q, autoescape=True),
                User.first_name.icontains(q, autoescape=True),
                User.last_name.icontains(q, autoescape=True),
            ),
            User.is_active.is_(True),
            User.id.not_in(members),
        )
        .order_by(User.email)
        .limit(8)
    )
    return [UserSuggestion(user_id=u.id, **_profile(u)) for u in rows]


@router.put("/{site_id}/members")
def upsert_member(
    body: MemberUpsert,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> MemberOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user with that email")
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.site_id == access.site.id
        )
    )
    if membership is None:
        db.add(Membership(user_id=user.id, site_id=access.site.id, role=body.role))
    else:
        membership.role = body.role
    db.commit()
    return MemberOut(user_id=user.id, role=body.role, **_profile(user))


@router.delete("/{site_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> None:
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id, Membership.site_id == access.site.id
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    db.delete(membership)
    db.commit()
