"""Settings a superadmin can change from the admin UI (System settings).

`SPECS` is the whole contract: a key listed there is shown, and when `editable` it is validated and can be
saved; everything else stays env-only. Making another setting editable is one entry (or one flag) here.

An override in `app_settings` wins over the env value. It is applied onto the shared `settings` object, so
code keeps reading `settings.<name>` and needs no change. The API process that saves a change applies it at
once, other API replicas reload every 30 seconds (app/main.py) and the worker reloads on every pass.

Secrets are write-only: stored encrypted with SETTINGS_ENCRYPTION_KEY and only ever reported as set or not.
"""

import logging
import typing
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Annotated, Any

from pydantic import Field, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import Settings, settings
from app.core.crypto import decrypt, encrypt
from app.models import AppSetting, User

log = logging.getLogger("loupebox.settings")

_PURPOSE = "settings"


def _mail_providers() -> list[str]:
    from app.notifications.registry import (
        all_providers,
    )  # the registry imports providers, which read settings

    return ["", *(p.key for p in all_providers() if p.uses_recipients)]


@dataclass(frozen=True)
class Spec:
    group: str
    label: str
    help: str = ""
    minimum: int | None = None
    maximum: int | None = None
    pattern: str | None = None
    choices: Callable[[], list[str]] | None = None  # Literal fields get theirs from the type
    secret: bool = False
    editable: bool = True  # False: shown for reference, changed in env only


_EMAIL = "Email"
_NOTIFY = "Notifications"
_INGEST = "Public feedback form"
_SIGNIN = "Sign-in and accounts"
_LIMITS = "Replies and data"
_SERVER = "Server"

SPECS: dict[str, Spec] = {
    # Email
    "mail_provider": Spec(
        _EMAIL,
        "Account mail provider",
        "Sends password resets and replies. Empty: the first configured one.",
        choices=_mail_providers,
    ),
    "notify_sender_email": Spec(_EMAIL, "Sender address", pattern=r"^$|^[^@\s]+@[^@\s]+$"),
    "notify_sender_name": Spec(_EMAIL, "Sender name"),
    "public_url": Spec(
        _EMAIL,
        "Admin UI address",
        "Used for links in emails. Links are left out when empty.",
        pattern=r"^$|^https?://[^\s/]+(/\S*)?$",
    ),
    "brevo_api_key": Spec(_EMAIL, "Brevo API key", secret=True),
    "smtp_host": Spec(_EMAIL, "SMTP host"),
    "smtp_port": Spec(_EMAIL, "SMTP port", "587 with starttls, 465 with ssl.", minimum=1, maximum=65535),
    "smtp_security": Spec(_EMAIL, "SMTP security", "none never sends the username and password."),
    "smtp_username": Spec(_EMAIL, "SMTP username"),
    "smtp_password": Spec(_EMAIL, "SMTP password", secret=True),
    "smtp_timeout": Spec(_EMAIL, "SMTP timeout (seconds)", minimum=1, maximum=120),
    # Notifications
    "notify_hourly_cap": Spec(
        _NOTIFY, "Emails per channel per hour", "The rest are rolled into one summary.", minimum=1
    ),
    "notify_summary_delay_minutes": Spec(_NOTIFY, "Summary delay (minutes)", minimum=1),
    "notify_max_recipients": Spec(_NOTIFY, "Recipients per channel", minimum=1, maximum=500),
    "notify_retention_days": Spec(_NOTIFY, "Keep sent notifications (days)", minimum=1),
    "worker_poll_seconds": Spec(_NOTIFY, "Worker poll interval (seconds)", minimum=1, maximum=300),
    # Public ingest
    "public_ip_limit": Spec(_INGEST, "Submissions per visitor IP", "Per rate-limit window.", minimum=1),
    "public_key_limit": Spec(_INGEST, "Submissions per site key", "Per rate-limit window.", minimum=1),
    "public_window_seconds": Spec(_INGEST, "Rate-limit window (seconds)", minimum=1),
    "default_site_daily_limit": Spec(_INGEST, "Daily limit for new sites", minimum=1),
    "dedupe_window_minutes": Spec(_INGEST, "Duplicate window (minutes)", minimum=0),
    "spam_link_threshold": Spec(
        _INGEST, "Links before quarantine", "Messages with more links than this go to spam.", minimum=0
    ),
    "challenge_ttl_seconds": Spec(_INGEST, "Challenge lifetime (seconds)", minimum=30),
    "challenge_ip_limit": Spec(_INGEST, "Challenges per visitor IP", "Per rate-limit window.", minimum=1),
    "challenge_key_limit": Spec(_INGEST, "Challenges per site key", "Per rate-limit window.", minimum=1),
    # Sign-in
    "access_token_minutes": Spec(_SIGNIN, "Session token lifetime (minutes)", minimum=1, maximum=120),
    "refresh_token_days": Spec(_SIGNIN, "Stay signed in for (days)", minimum=1, maximum=365),
    "login_ip_limit": Spec(_SIGNIN, "Sign-in attempts per IP", "Per sign-in window.", minimum=1),
    "login_account_limit": Spec(_SIGNIN, "Sign-in attempts per account", "Per sign-in window.", minimum=1),
    "login_window_seconds": Spec(_SIGNIN, "Sign-in window (seconds)", minimum=1),
    "login_failure_limit": Spec(
        _SIGNIN, "Failed passwords before lockout", "Per email, from any IP.", minimum=1
    ),
    "login_failure_window_seconds": Spec(_SIGNIN, "Lockout window (seconds)", minimum=1),
    "mfa_token_minutes": Spec(_SIGNIN, "Time to enter a 2FA code (minutes)", minimum=1, maximum=30),
    "mfa_hourly_limit": Spec(_SIGNIN, "2FA attempts per user per hour", minimum=1),
    "totp_issuer": Spec(_SIGNIN, "Authenticator app label", "Changing it only affects new 2FA setups."),
    "password_reset_minutes": Spec(_SIGNIN, "Reset link lifetime (minutes)", minimum=5, maximum=1440),
    "password_reset_email_limit": Spec(_SIGNIN, "Reset emails per address per hour", minimum=1),
    "password_reset_ip_limit": Spec(_SIGNIN, "Reset requests per IP per hour", minimum=1),
    # Replies and data
    "reply_max_per_item": Spec(_LIMITS, "Replies per feedback item", minimum=1),
    "reply_site_hourly_limit": Spec(_LIMITS, "Replies per site per hour", minimum=1),
    "bulk_max_ids": Spec(_LIMITS, "Items per bulk action", minimum=1, maximum=1000),
    "export_max_rows": Spec(_LIMITS, "Rows per CSV export", minimum=1),
    "audit_retention_days": Spec(_LIMITS, "Keep audit log (days)", "0 keeps it forever.", minimum=0),
    # Server: read at startup or security-sensitive, so env only for now.
    "environment": Spec(_SERVER, "Environment", editable=False),
    "admin_origins": Spec(_SERVER, "Admin UI origins", editable=False),
    "trust_proxy": Spec(_SERVER, "Trust X-Forwarded-For", editable=False),
    "cookie_secure": Spec(_SERVER, "Secure cookies", editable=False),
    "cookie_samesite": Spec(_SERVER, "Cookie SameSite", editable=False),
    "public_require_origin": Spec(_SERVER, "Require Origin on public form", editable=False),
    "webhook_allow_private": Spec(_SERVER, "Allow private webhook targets", editable=False),
    "max_body_bytes": Spec(_SERVER, "Largest request body (bytes)", editable=False),
    "avatar_max_bytes": Spec(_SERVER, "Largest avatar (bytes)", editable=False),
}

_shadowed: dict[str, Any] = {}  # the env value each active override hides
# Taken now: pydantic adds every later setattr (ours, or a test's monkeypatch) to model_fields_set.
_FROM_ENV = frozenset(settings.model_fields_set)


def _annotation(key: str) -> Any:
    return Settings.model_fields[key].annotation


@cache
def _adapter(key: str) -> TypeAdapter:
    s = SPECS[key]
    return TypeAdapter(Annotated[_annotation(key), Field(ge=s.minimum, le=s.maximum, pattern=s.pattern)])


def _kind(key: str) -> str:
    ann = _annotation(key)
    origin = typing.get_origin(ann)
    if origin is list:
        return "list"
    return {int: "integer", bool: "boolean"}.get(ann, "string")


def _choices(key: str) -> list[str] | None:
    spec, ann = SPECS[key], _annotation(key)
    if spec.choices:
        return spec.choices()
    return list(typing.get_args(ann)) if typing.get_origin(ann) is typing.Literal else None


def validate(key: str, value: Any) -> Any:
    """The value as the setting's type, or ValueError with a message for people."""
    spec = SPECS.get(key)
    if spec is None or not spec.editable:
        raise ValueError("can't be changed here")
    try:
        value = _adapter(key).validate_python(value)
    except ValidationError as e:
        raise ValueError(e.errors()[0]["msg"]) from None
    options = _choices(key)
    if options is not None and value not in options:
        raise ValueError(f"must be one of: {', '.join(repr(o) for o in options)}")
    return value


def _apply(overrides: dict[str, Any]) -> None:
    for key in set(_shadowed) - set(overrides):
        setattr(settings, key, _shadowed.pop(key))
    for key, value in overrides.items():
        _shadowed.setdefault(key, getattr(settings, key))
        setattr(settings, key, value)


def load(db: Session) -> None:
    """Apply the saved overrides, dropping any that are no longer editable or valid."""
    overrides = {}
    for row in db.scalars(select(AppSetting)):
        spec = SPECS.get(row.key)
        value = decrypt(_PURPOSE, row.value) if spec and spec.secret else row.value
        try:
            overrides[row.key] = validate(row.key, value)
        except ValueError as e:
            log.warning("ignoring saved setting %s: %s", row.key, e)
    _apply(overrides)


def reset() -> None:
    """Back to env values only (tests)."""
    _apply({})


def describe() -> list[dict[str, Any]]:
    out = []
    for key, spec in SPECS.items():
        current, hide = getattr(settings, key), spec.secret
        source = "ui" if key in _shadowed else "env" if key in _FROM_ENV else "default"
        out.append(
            {
                "key": key,
                "group": spec.group,
                "label": spec.label,
                "help": spec.help,
                "type": _kind(key),
                "minimum": spec.minimum,
                "maximum": spec.maximum,
                "choices": _choices(key),
                "secret": spec.secret,
                "editable": spec.editable,
                "source": source,
                "configured": bool(current),
                "value": None if hide else current,
                "env_value": None if hide else _shadowed.get(key, current),
                "default": None if hide else Settings.model_fields[key].default,
            }
        )
    return out


def save(db: Session, actor: User, changes: dict[str, Any]) -> list[str]:
    """Validate every change (all or nothing), store it, audit it, commit and apply. `None` resets a key to
    its env value. Returns the keys that changed. Raises ValueError naming the first bad setting."""
    clean = {}
    for key, value in changes.items():
        try:
            clean[key] = None if value is None else validate(key, value)
        except ValueError as e:
            label = SPECS[key].label if key in SPECS else key
            raise ValueError(f"{label}: {e}") from None
    rows = {r.key: r for r in db.scalars(select(AppSetting).where(AppSetting.key.in_(clean)))}
    details: dict[str, Any] = {}
    for key, value in clean.items():
        spec, row, before = SPECS[key], rows.get(key), getattr(settings, key)
        if value is None:
            if row is None:
                continue
            db.delete(row)
            after = _shadowed.get(key, before)
        else:
            stored = encrypt(_PURPOSE, value) if spec.secret else value
            if row is None:
                db.add(AppSetting(key=key, value=stored, updated_by=actor.email))
            else:
                row.value, row.updated_by = stored, actor.email
            after = value
        details[key] = "changed" if spec.secret else {"from": before, "to": after, "reset": value is None}
    if details:
        names = ", ".join(SPECS[k].label for k in details)
        audit(
            db,
            actor,
            "settings.update",
            f"Changed system settings: {names}",
            target_type="settings",
            target_id="system",
            details=details,
        )
    db.commit()
    load(db)
    return list(details)
