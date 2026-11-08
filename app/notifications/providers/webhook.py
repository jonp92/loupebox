"""Signed JSON webhooks, following the Standard Webhooks signing scheme (standardwebhooks.com).

Each delivery is a POST with `webhook-id` (stable across retries, use it to dedupe),
`webhook-timestamp` (unix seconds) and `webhook-signature` (`v1,<base64 HMAC-SHA256>` over
`{id}.{timestamp}.{body}`, keyed with the base64 part of the channel's `whsec_...` secret).

The target is checked at send time and the request goes to the address that was checked
(app/core/netguard.py); redirects are never followed and the response body is never read.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import netguard
from app.core.config import settings
from app.notifications.base import Message, NotificationProvider, SendResult
from app.notifications.registry import register_provider

TIMEOUT = httpx.Timeout(10.0)
# Worth another try: the receiver is busy or down. Everything else 4xx is permanent.
RETRYABLE = {408, 425, 429}
SECRET_PREFIX = "whsec_"


def generate_secret() -> str:
    return SECRET_PREFIX + base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes).decode()


def sign(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix(SECRET_PREFIX))
    digest = hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


class WebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        title="Endpoint URL", max_length=netguard.MAX_URL, description="Must be a public https URL."
    )

    include_reply_text: bool = Field(
        default=False,
        title="Include the text of replies",
        description="Adds the reply text to feedback.replied events. Off by default: replies are private to "
        "your team and the person who wrote in.",
    )

    @field_validator("url")
    @classmethod
    def _safe_url(cls, v: str) -> str:
        v = v.strip()
        try:
            netguard.parse(v, allow_private=settings.webhook_allow_private)
        except netguard.UnsafeTarget as exc:
            raise ValueError(str(exc)) from exc
        return v


def _transport() -> httpx.BaseTransport | None:
    """Seam for tests (httpx.MockTransport). None uses the real network."""
    return None


@register_provider
class WebhookProvider(NotificationProvider):
    key = "webhook"
    label = "Webhook (signed JSON)"
    ConfigModel = WebhookConfig
    uses_recipients = False
    rate_capped = False
    signs = True

    def new_secret(self) -> str:
        return generate_secret()

    def check_config(self, config: BaseModel) -> None:
        try:
            netguard.resolve(config.url, allow_private=settings.webhook_allow_private)  # type: ignore[attr-defined]
        except netguard.UnsafeTarget as exc:
            raise ValueError(str(exc)) from exc
        except netguard.ResolutionError as exc:
            raise ValueError(str(exc)) from exc

    def send(self, message: Message, config: BaseModel) -> SendResult:
        if not message.secret or message.event is None:
            return SendResult.failed("webhook: nothing to sign")
        try:
            targets = netguard.resolve(config.url, allow_private=settings.webhook_allow_private)  # type: ignore[attr-defined]
        except netguard.UnsafeTarget as exc:
            return SendResult.failed(f"webhook blocked: {exc}")
        except netguard.ResolutionError as exc:
            return SendResult.retry(f"webhook: {exc}")

        body = json.dumps(message.event, separators=(",", ":"), ensure_ascii=False).encode()
        msg_id = str(message.event["id"])
        last_error = "no address to connect to"
        with httpx.Client(timeout=TIMEOUT, transport=_transport(), trust_env=False) as client:
            for target in targets:
                timestamp = int(time.time())
                headers = {
                    "Host": target.host_header,
                    "Content-Type": "application/json",
                    "User-Agent": f"{settings.app_name}-webhook/{settings.app_version}",
                    "webhook-id": msg_id,
                    "webhook-timestamp": str(timestamp),
                    "webhook-signature": sign(message.secret, msg_id, timestamp, body),
                }
                extensions = {"sni_hostname": target.tls_name} if target.tls_name else {}
                try:
                    with client.stream(
                        "POST", target.url, content=body, headers=headers, extensions=extensions
                    ) as r:
                        status = r.status_code
                except httpx.ConnectError as exc:
                    last_error = f"webhook: {type(exc).__name__}"
                    continue  # try the next address
                except httpx.HTTPError as exc:  # timeouts, resets, TLS failures
                    return SendResult.retry(f"webhook: {type(exc).__name__}")
                return _result(status, msg_id)
        return SendResult.retry(last_error)


def _result(status: int, msg_id: str) -> SendResult:
    if 200 <= status < 300:
        return SendResult.sent(msg_id)
    if 300 <= status < 400:
        return SendResult.failed(f"webhook {status}: redirects are not followed, use the final URL")
    if status in RETRYABLE or status >= 500:
        return SendResult.retry(f"webhook {status}")
    return SendResult.failed(f"webhook {status}")
