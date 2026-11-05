"""Plain SMTP email, for installs without a Brevo account (or that prefer their own relay).

Settings are operator-owned (SMTP_*), like Brevo's. TLS is verified against the system trust store, and
a `starttls` server that doesn't offer STARTTLS is an error, never a silent fall back to plaintext.
`none` sends unencrypted and therefore never sends credentials: with a username set it counts as not
configured. One connection per send; one message per recipient so addresses stay private from each other.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.notifications.base import Message, NotificationProvider, SendResult
from app.notifications.registry import register_provider

log = logging.getLogger("loupebox.smtp")

ERROR_MAX = 200


class SmtpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _tls_context() -> ssl.SSLContext:
    """Seam for tests. The default verifies certificates and host names."""
    return ssl.create_default_context()


def _sender_domain() -> str:
    return settings.notify_sender_email.rsplit("@", 1)[-1] or "localhost"


def _connect() -> smtplib.SMTP:
    """An open, encrypted (as configured) and authenticated connection. Raises smtplib/OS errors."""
    kwargs = {"host": settings.smtp_host, "port": settings.smtp_port, "timeout": settings.smtp_timeout}
    # EHLO with the sender's domain: the container's own hostname looks like spam to receiving servers.
    kwargs["local_hostname"] = _sender_domain()
    if settings.smtp_security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(context=_tls_context(), **kwargs)
    else:
        server = smtplib.SMTP(**kwargs)
    try:
        server.ehlo()
        if settings.smtp_security == "starttls":
            server.starttls(context=_tls_context())  # SMTPNotSupportedError if the server can't
            server.ehlo()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
    except BaseException:
        server.close()
        raise
    return server


def _reply_to(value: str | None) -> str | None:
    """Submitter-supplied, so only a plausible single address is allowed into a header."""
    if value and "@" in value and not any(c in value for c in '\r\n<>,;" '):
        return value
    return None


def build(message: Message, address: str) -> EmailMessage:
    out = EmailMessage()
    out["From"] = formataddr((settings.notify_sender_name, settings.notify_sender_email))
    out["To"] = address
    out["Subject"] = message.subject
    out["Date"] = formatdate(localtime=False)
    out["Message-ID"] = make_msgid(domain=_sender_domain())
    if reply := _reply_to(message.reply_to):
        out["Reply-To"] = reply
    if message.tags:
        out["X-Loupebox-Tags"] = ",".join(message.tags)
    out.set_content(message.text)
    if message.html:
        out.add_alternative(message.html, subtype="html")
    return out


def _text(code: int | None, detail: object) -> str:
    raw = detail.decode("utf-8", "replace") if isinstance(detail, bytes) else str(detail)
    return (
        f"smtp {code}: {' '.join(raw.split())[:ERROR_MAX]}"
        if code
        else f"smtp: {' '.join(raw.split())[:ERROR_MAX]}"
    )


def _classify(exc: smtplib.SMTPException | OSError) -> SendResult:
    """4xx replies and network trouble are worth retrying; 5xx replies and configuration errors are not."""
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return SendResult.failed("smtp: server does not offer STARTTLS; refusing to send unencrypted")
    if isinstance(exc, ssl.SSLCertVerificationError):
        return SendResult.failed(f"smtp: TLS certificate not trusted ({exc.verify_message})")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        code = next(iter(exc.recipients.values()))[0]
        return (
            SendResult.failed(f"smtp {code}: recipient refused")
            if code >= 500
            else SendResult.retry(f"smtp {code}: recipient deferred")
        )
    if isinstance(exc, smtplib.SMTPResponseException):  # auth, sender, data, ... all carry a code
        code = exc.smtp_code
        detail = _text(code, exc.smtp_error)
        return SendResult.failed(detail) if code >= 500 else SendResult.retry(detail)
    return SendResult.retry(f"smtp: {type(exc).__name__}")  # disconnects, timeouts, refused connections


@register_provider
class SmtpProvider(NotificationProvider):
    key = "smtp"
    label = "SMTP (email)"
    ConfigModel = SmtpConfig

    def is_configured(self) -> bool:
        if not (settings.smtp_host and settings.notify_sender_email):
            return False
        # Never send a password in the clear.
        return not (settings.smtp_security == "none" and settings.smtp_username)

    def send(self, message: Message, config: BaseModel) -> SendResult:
        try:
            server = _connect()
        except (smtplib.SMTPException, OSError) as exc:
            return _classify(exc)
        ids: list[str] = []
        retry: str | None = None
        failed: str | None = None
        try:
            for address in message.to:
                try:
                    email = build(message, address)
                except ValueError:  # e.g. a header the email library refuses (line breaks)
                    failed = failed or "smtp: message could not be built"
                    continue
                try:
                    server.send_message(email)
                    ids.append(str(email["Message-ID"]))
                except (smtplib.SMTPException, OSError) as exc:
                    result = _classify(exc)
                    if result.status == "retry":
                        retry = retry or result.error
                        if isinstance(exc, (smtplib.SMTPServerDisconnected, OSError)):
                            break  # the connection is gone; the rest wait for the retry
                    else:
                        failed = failed or result.error
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                server.close()
        # A retry re-sends to everyone, so a recipient may get a duplicate: delivery is at-least-once.
        if retry:
            return SendResult.retry(retry)
        if failed:
            return SendResult.failed(failed)
        return SendResult.sent(",".join(ids)[:128] or None)
