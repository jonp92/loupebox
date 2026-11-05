import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, get_current_user, require_superadmin, site_access
from app.challenges.registry import OFF, all_verifiers, get_verifier
from app.core.audit import audit, changed, snapshot
from app.core.config import settings
from app.core.origins import public_origins
from app.core.security import new_public_key
from app.db.session import get_db
from app.models import Feedback, Membership, Role, Site, User
from app.schemas.site import (
    MemberOut,
    MemberUpsert,
    SiteCreate,
    SiteOut,
    SiteUpdate,
    UserSuggestion,
    VerifierOut,
)

router = APIRouter(prefix="/sites", tags=["sites"])

_SITE_FIELDS = ("name", "allowed_origins", "is_active", "daily_limit", "challenge_mode", "challenge_config")


def _profile(u: User) -> dict:
    return {
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "avatar_url": u.avatar_url,
    }


def _unassign(db: Session, site: Site, user_id: uuid.UUID) -> None:
    """Only editors and admins can hold assignments, so losing that access clears them."""
    db.execute(
        update(Feedback)
        .where(Feedback.site_id == site.id, Feedback.assignee_id == user_id)
        .values(assignee_id=None)
    )


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
    body: SiteCreate, actor: User = Depends(require_superadmin), db: Session = Depends(get_db)
) -> SiteOut:
    site = Site(
        id=uuid.uuid4(),
        name=body.name,
        public_key=new_public_key(),
        allowed_origins=body.allowed_origins,
        daily_limit=body.daily_limit or settings.default_site_daily_limit,
    )
    db.add(site)
    audit(
        db,
        actor,
        "site.create",
        f"Created site {site.name}",
        target_type="site",
        target_id=site.id,
        site=site,
        details={"name": site.name, "allowed_origins": site.allowed_origins, "daily_limit": site.daily_limit},
    )
    db.commit()
    public_origins.invalidate()
    return _out(site, Role.admin)


@router.get("/{site_id}")
def get_site(access: SiteAccess = Depends(site_access(Role.viewer))) -> SiteOut:
    return _out(access.site, access.role)


def _apply_challenge(site: Site, mode: str | None, config: dict | None) -> None:
    """Validate and store the challenge mode/config. Changing mode without a config resets to that
    verifier's defaults; "off" clears the config."""
    if mode is None and config is None:
        return
    mode = mode if mode is not None else site.challenge_mode
    if mode == OFF:
        site.challenge_mode, site.challenge_config = OFF, {}
        return
    verifier = get_verifier(mode)
    if verifier is None:
        raise HTTPException(422, f"Unknown challenge mode {mode!r}")
    if config is None:
        config = site.challenge_config if mode == site.challenge_mode else {}
    try:
        site.challenge_config = verifier.ConfigModel.model_validate(config).model_dump()
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)[0]["msg"])
    site.challenge_mode = mode


@router.patch("/{site_id}")
def update_site(
    body: SiteUpdate,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> SiteOut:
    before = snapshot(access.site, _SITE_FIELDS)
    changes = body.model_dump(exclude_unset=True)
    _apply_challenge(access.site, changes.pop("challenge_mode", None), changes.pop("challenge_config", None))
    for field, value in changes.items():
        if value is None:
            continue
        setattr(access.site, field, value)
    diff = changed(before, access.site)
    if diff:
        audit(
            db,
            access.user,
            "site.update",
            f"Updated settings of {access.site.name}: {', '.join(diff)}",
            target_type="site",
            target_id=access.site.id,
            site=access.site,
            details=diff,
        )
    db.commit()
    public_origins.invalidate()
    return _out(access.site, access.role)


@router.get("/{site_id}/challenge-verifiers")
def list_challenge_verifiers(_: SiteAccess = Depends(site_access(Role.admin))) -> list[VerifierOut]:
    """Challenge modes a site can switch to, with each one's settings schema (the UI renders from it)."""
    return [
        VerifierOut(key=v.key, label=v.label, config_schema=v.ConfigModel.model_json_schema())
        for v in all_verifiers()
    ]


@router.post("/{site_id}/rotate-key")
def rotate_key(
    access: SiteAccess = Depends(site_access(Role.admin)), db: Session = Depends(get_db)
) -> SiteOut:
    """Issue a new public key; the old one stops working immediately."""
    access.site.public_key = new_public_key()
    audit(  # never the key itself
        db,
        access.user,
        "site.rotate_key",
        f"Rotated the API key of {access.site.name}",
        target_type="site",
        target_id=access.site.id,
        site=access.site,
    )
    db.commit()
    return _out(access.site, access.role)


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_site(
    site_id: uuid.UUID, actor: User = Depends(require_superadmin), db: Session = Depends(get_db)
) -> None:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    audit(
        db,
        actor,
        "site.delete",
        f"Deleted site {site.name}",
        target_type="site",
        target_id=site.id,
        site=site,
    )
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
        select(Membership).where(Membership.user_id == user.id, Membership.site_id == access.site.id)
    )
    if membership is None:
        db.add(Membership(user_id=user.id, site_id=access.site.id, role=body.role))
        audit(
            db,
            access.user,
            "member.add",
            f"Added {user.email} to {access.site.name} as {body.role.value}",
            target_type="user",
            target_id=user.id,
            site=access.site,
            details={"email": user.email, "role": body.role.value},
        )
    elif membership.role != body.role:
        audit(
            db,
            access.user,
            "member.role_change",
            f"Changed {user.email} on {access.site.name} from {membership.role.value} to {body.role.value}",
            target_type="user",
            target_id=user.id,
            site=access.site,
            details={"email": user.email, "role": {"from": membership.role.value, "to": body.role.value}},
        )
        membership.role = body.role
        if body.role == Role.viewer:
            _unassign(db, access.site, user.id)
    db.commit()
    return MemberOut(user_id=user.id, role=body.role, **_profile(user))


@router.delete("/{site_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> None:
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user_id, Membership.site_id == access.site.id)
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    removed = db.get(User, user_id)
    email = removed.email if removed else str(user_id)
    audit(
        db,
        access.user,
        "member.remove",
        f"Removed {email} from {access.site.name}",
        target_type="user",
        target_id=user_id,
        site=access.site,
        details={"email": email, "role": membership.role.value},
    )
    _unassign(db, access.site, user_id)
    db.delete(membership)
    db.commit()
