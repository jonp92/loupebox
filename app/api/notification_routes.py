import uuid
from datetime import UTC, datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, get_current_user, site_access
from app.core import crypto
from app.core.audit import audit, changed, snapshot
from app.core.rate_limit import enforce
from app.db.session import get_db
from app.models import Membership, NotificationChannel, NotificationOutbox, Role, User
from app.notifications.base import Message, NotificationProvider
from app.notifications.layout import quote, render
from app.notifications.registry import all_providers, get_provider
from app.schemas.notification import (
    ChannelCreate,
    ChannelCreated,
    ChannelOut,
    ChannelUpdate,
    DeliveryOut,
    ProviderOut,
    SecretOut,
    TestResult,
)

router = APIRouter(tags=["notifications"])

# Provider settings and recipient addresses can be sensitive: the log records that they changed, not the values.
_CHANNEL_FIELDS = ("name", "enabled", "events", "min_role", "extra_recipients", "config")
_CHANNEL_REDACTED = ("config", "extra_recipients")

MAX_CHANNELS_PER_SITE = 10
DELIVERIES_SHOWN = 50
TEST_LIMIT, TEST_WINDOW = 5, 600  # test sends per admin per 10 minutes


def _provider(key: str) -> NotificationProvider:
    provider = get_provider(key)
    if provider is None:
        raise HTTPException(422, f"Unknown provider: {key}")
    return provider


def _validated_config(provider: NotificationProvider, config: dict) -> dict:
    """Parse through the provider's model: rejects bad values, drops fields it doesn't declare."""
    try:
        model = provider.ConfigModel.model_validate(config)
    except ValidationError as exc:
        detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg'].removeprefix('Value error, ')}" for e in exc.errors())
        raise HTTPException(422, f"Invalid config: {detail}") from exc
    try:
        provider.check_config(model)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid config: {exc}") from exc
    return model.model_dump(mode="json")


def _require_configured(provider: NotificationProvider) -> None:
    if not provider.is_configured():
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{provider.label} is not configured on the server"
        )


def _channel(db: Session, access: SiteAccess, channel_id: uuid.UUID) -> NotificationChannel:
    channel = db.get(NotificationChannel, channel_id)
    if channel is None or channel.site_id != access.site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    return channel


@router.get("/notifications/providers")
def list_providers(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ProviderOut]:
    """Available providers. Limited to people who can manage notifications somewhere."""
    is_admin = user.is_superadmin or db.scalar(
        select(Membership.id).where(Membership.user_id == user.id, Membership.role == Role.admin).limit(1)
    )
    if not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {Role.admin.value} role")
    return [
        ProviderOut(
            key=p.key,
            label=p.label,
            configured=p.is_configured(),
            uses_recipients=p.uses_recipients,
            signs=p.signs,
            config_schema=p.ConfigModel.model_json_schema(),
        )
        for p in all_providers()
    ]


@router.get("/sites/{site_id}/notifications")
def list_channels(
    access: SiteAccess = Depends(site_access(Role.admin)), db: Session = Depends(get_db)
) -> list[ChannelOut]:
    rows = db.scalars(
        select(NotificationChannel)
        .where(NotificationChannel.site_id == access.site.id)
        .order_by(NotificationChannel.created_at)
    )
    return [ChannelOut.model_validate(c) for c in rows]


@router.post("/sites/{site_id}/notifications", status_code=status.HTTP_201_CREATED)
def create_channel(
    body: ChannelCreate,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> ChannelCreated:
    provider = _provider(body.provider)
    config = _validated_config(provider, body.config)
    if body.enabled:
        _require_configured(provider)
    count = db.scalar(
        select(func.count())
        .select_from(NotificationChannel)
        .where(NotificationChannel.site_id == access.site.id)
    )
    if (count or 0) >= MAX_CHANNELS_PER_SITE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"At most {MAX_CHANNELS_PER_SITE} channels per site")
    channel = NotificationChannel(
        id=uuid.uuid4(),
        site_id=access.site.id,
        provider=provider.key,
        name=body.name,
        enabled=body.enabled,
        config=config,
        events=body.events,
        min_role=body.min_role,
        extra_recipients=body.extra_recipients,
    )
    secret = provider.new_secret() if provider.signs else None
    if secret:
        channel.secret = crypto.encrypt("webhook", secret)
    db.add(channel)
    audit(
        db, access.user, "channel.create", f'Added the {provider.label} channel "{channel.name}" to {access.site.name}',
        target_type="channel", target_id=channel.id, site=access.site,
        details={"provider": provider.key, "name": channel.name, "enabled": channel.enabled},
    )
    db.commit()
    return ChannelCreated.model_validate({**ChannelOut.model_validate(channel).model_dump(), "secret": secret})


@router.patch("/sites/{site_id}/notifications/{channel_id}")
def update_channel(
    channel_id: uuid.UUID,
    body: ChannelUpdate,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> ChannelOut:
    channel = _channel(db, access, channel_id)
    provider = _provider(channel.provider)
    changes = body.model_dump(exclude_unset=True)
    for field in ("name", "enabled", "events", "min_role", "extra_recipients", "config"):
        if changes.get(field, 0) is None:  # an explicit null means "leave as is", like site PATCH
            changes.pop(field)
    if "config" in changes:
        changes["config"] = _validated_config(provider, changes["config"])
    if changes.get("enabled", channel.enabled):
        _require_configured(provider)
    before = snapshot(channel, _CHANNEL_FIELDS)
    for field, value in changes.items():
        setattr(channel, field, value)
    diff = changed(before, channel, redact=_CHANNEL_REDACTED)
    if diff:
        audit(
            db, access.user, "channel.update", f'Updated the channel "{channel.name}" on {access.site.name}: {", ".join(diff)}',
            target_type="channel", target_id=channel.id, site=access.site, details=diff,
        )
    db.commit()
    return ChannelOut.model_validate(channel)


@router.delete("/sites/{site_id}/notifications/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(
    channel_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> None:
    channel = _channel(db, access, channel_id)
    audit(
        db, access.user, "channel.delete", f'Deleted the channel "{channel.name}" from {access.site.name}',
        target_type="channel", target_id=channel.id, site=access.site, details={"provider": channel.provider, "name": channel.name},
    )
    db.delete(channel)
    db.commit()


@router.post("/sites/{site_id}/notifications/{channel_id}/rotate-secret")
def rotate_secret(
    channel_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> SecretOut:
    """Replace the signing secret. The old one stops working immediately; the new one is shown once."""
    channel = _channel(db, access, channel_id)
    provider = _provider(channel.provider)
    if not provider.signs:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{provider.label} channels have no signing secret")
    secret = provider.new_secret()
    channel.secret = crypto.encrypt("webhook", secret)
    audit(
        db, access.user, "channel.rotate_secret", f'Rotated the signing secret of "{channel.name}" on {access.site.name}',
        target_type="channel", target_id=channel.id, site=access.site, details={"secret": "changed"},
    )
    db.commit()
    return SecretOut(secret=secret)


@router.post("/sites/{site_id}/notifications/{channel_id}/test")
def send_test(
    channel_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> TestResult:
    """Send one message straight through the provider, only to the caller. Not queued or capped."""
    channel = _channel(db, access, channel_id)
    provider = _provider(channel.provider)
    _require_configured(provider)
    config = provider.ConfigModel.model_validate(channel.config)
    enforce(f"notif-test:{access.user.id}", TEST_LIMIT, TEST_WINDOW)

    to = access.user.email if provider.uses_recipients else None
    site_name = " ".join(access.site.name.split())
    result = provider.send(
        Message(
            to=[to] if to else [],
            subject=f"Test notification for {' '.join(access.site.name.split())}",
            text=f'This is a test from the "{channel.name}" channel. Notifications are working.',
            html=render(
                heading="Notifications are working",
                preheader="This is a test notification.",
                body=quote(escape(f'This is a test from the "{channel.name}" channel.')),
                link=None,
                site=" ".join(access.site.name.split()),
            ),
            tags=["test"],
            event={
                "id": str(uuid.uuid4()),
                "type": "test",
                "created_at": datetime.now(UTC).isoformat(),
                "site": {"id": str(access.site.id), "name": site_name},
                "data": {"message": f'Test from the "{channel.name}" channel.'},
            },
            secret=crypto.decrypt("webhook", channel.secret) if channel.secret else None,
        ),
        config,
    )
    return TestResult(status=result.status, error=result.error, to=to)


@router.get("/sites/{site_id}/notifications/deliveries")
def list_deliveries(
    access: SiteAccess = Depends(site_access(Role.admin)), db: Session = Depends(get_db)
) -> list[DeliveryOut]:
    rows = db.execute(
        select(NotificationOutbox, NotificationChannel.name)
        .outerjoin(NotificationChannel, NotificationChannel.id == NotificationOutbox.channel_id)
        .where(NotificationOutbox.site_id == access.site.id)
        .order_by(NotificationOutbox.created_at.desc())
        .limit(DELIVERIES_SHOWN)
    )
    return [
        DeliveryOut(
            id=r.id,
            channel_id=r.channel_id,
            channel_name=name,
            event_type=r.event_type,
            status=r.status,
            attempts=r.attempts,
            summary=r.summary_id is not None,
            last_error=r.last_error,
            created_at=r.created_at,
            next_attempt_at=r.next_attempt_at,
            sent_at=r.sent_at,
        )
        for r, name in rows
    ]
