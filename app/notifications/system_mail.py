"""Account mail (password reset): sent straight through a mail provider, not through the outbox.

The outbox keeps its payloads for `NOTIFY_RETENTION_DAYS`, and a reset email carries a live token, so it
never goes there. The cost is no retries: a failed send is logged and the user asks again.
"""

import logging
from html import escape

from app.core.config import settings
from app.notifications.base import Message, NotificationProvider, SendResult
from app.notifications.layout import render
from app.notifications.registry import all_providers

log = logging.getLogger("ganymede.system_mail")

_P = 'class="text" style="margin:12px 0 0;color:#171923;font-size:15px;line-height:1.5"'
_FOOTER = "You get this because of an action on your Ganymede account."


def mail_provider() -> NotificationProvider | None:
    """The configured email provider (one that sends to people) that account mail uses."""
    candidates = [p for p in all_providers() if p.uses_recipients]
    if settings.mail_provider:
        candidates = [p for p in candidates if p.key == settings.mail_provider]
    return next((p for p in candidates if p.is_configured()), None)


def password_reset_available() -> bool:
    """Links need to point at the admin UI, and something has to be able to send them."""
    return bool(settings.public_url) and mail_provider() is not None


def send_system_email(to: str, subject: str, text: str, html: str, tag: str) -> SendResult:
    provider = mail_provider()
    if provider is None:
        return SendResult.failed("no mail provider is configured")
    message = Message(to=[to], subject=subject, text=text, html=html, tags=[tag])
    try:
        return provider.send(message, provider.ConfigModel())
    except Exception as exc:  # a provider bug must not break the request that triggered the mail
        log.exception("mail provider %s raised", provider.key)
        return SendResult.retry(f"{type(exc).__name__}: {exc}")


def reset_link(token: str) -> str:
    # In the fragment so the token never appears in server logs, proxies or Referer headers.
    return f"{settings.public_url.rstrip('/')}/reset-password#token={token}"


def password_reset_message(token: str) -> tuple[str, str, str]:
    link = reset_link(token)
    minutes = settings.password_reset_minutes
    lead = "Someone asked to reset the password for your Ganymede account."
    note = f"The link works once and expires in {minutes} minutes. If this wasn't you, ignore this email: your password stays as it is."
    text = f"{lead}\n\nChoose a new password: {link}\n\n{note}"
    body = f'<p {_P}>{escape(lead)}</p><p {_P}>{escape(note)}</p>'
    html = render(
        heading="Reset your password", preheader=lead, body=body, link=link,
        site="Account security", button_label="Choose a new password", footer=_FOOTER,
    )
    return "Reset your Ganymede password", text, html


def password_changed_message() -> tuple[str, str, str]:
    lead = "The password for your Ganymede account was just changed, and you were signed out everywhere."
    note = "If you did this, there is nothing more to do. If not, ask a superadmin to reset your password and review your account."
    text = f"{lead}\n\n{note}"
    html = render(
        heading="Your password was changed", preheader=lead,
        body=f'<p {_P}>{escape(lead)}</p><p {_P}>{escape(note)}</p>',
        link=None, site="Account security", footer=_FOOTER,
    )
    return "Your Ganymede password was changed", text, html
