"""Brevo transactional email: https://developers.brevo.com/reference/sendtransacemail"""

import httpx
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.notifications.base import Message, NotificationProvider, SendResult
from app.notifications.registry import register_provider

API_URL = "https://api.brevo.com/v3/smtp/email"
TIMEOUT = 10.0
# Permanent: bad request, bad key, key not allowed. Retrying cannot fix these.
PERMANENT = {400, 401, 403}


class BrevoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _transport() -> httpx.BaseTransport | None:
    """Seam for tests (httpx.MockTransport). None uses the real network."""
    return None


@register_provider
class BrevoProvider(NotificationProvider):
    key = "brevo"
    label = "Brevo (email)"
    ConfigModel = BrevoConfig

    def is_configured(self) -> bool:
        return bool(settings.brevo_api_key and settings.notify_sender_email)

    def send(self, message: Message, config: BaseModel) -> SendResult:
        # One call per recipient so addresses are never exposed to each other.
        ids: list[str] = []
        retry: str | None = None
        failed: str | None = None
        with httpx.Client(timeout=TIMEOUT, transport=_transport()) as client:
            for address in message.to:
                result = self._send_one(client, message, address)
                if result.status == "sent":
                    ids.append(result.message_id or "")
                elif result.status == "retry":
                    retry = retry or result.error
                else:
                    failed = failed or result.error
        # A retry re-sends to everyone, so a recipient may get a duplicate: delivery is at-least-once.
        if retry:
            return SendResult.retry(retry)
        if failed:
            return SendResult.failed(failed)
        return SendResult.sent(",".join(i for i in ids if i)[:128] or None)

    def _send_one(self, client: httpx.Client, message: Message, address: str) -> SendResult:
        body: dict = {
            "sender": {"email": settings.notify_sender_email, "name": settings.notify_sender_name},
            "to": [{"email": address}],
            "subject": message.subject,
            "textContent": message.text,
        }
        if message.html:
            body["htmlContent"] = message.html
        if message.reply_to:
            body["replyTo"] = {"email": message.reply_to}
        if message.tags:
            body["tags"] = message.tags
        try:
            r = client.post(
                API_URL,
                json=body,
                headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
            )
        except httpx.HTTPError as exc:  # timeouts and connection errors
            return SendResult.retry(f"brevo: {type(exc).__name__}")
        if r.status_code == 201:
            return SendResult.sent(_message_id(r))
        # Brevo's error body is {"code", "message"}. Log neither the key nor the message content.
        detail = _error_text(r)
        if r.status_code in PERMANENT or (400 <= r.status_code < 500 and r.status_code != 429):
            return SendResult.failed(f"brevo {r.status_code}: {detail}")
        return SendResult.retry(f"brevo {r.status_code}: {detail}")


def _message_id(r: httpx.Response) -> str | None:
    try:
        return str(r.json().get("messageId") or "") or None
    except ValueError:
        return None


def _error_text(r: httpx.Response) -> str:
    try:
        data = r.json()
        return f"{data.get('code', '')} {data.get('message', '')}".strip()[:200]
    except ValueError:
        return ""
