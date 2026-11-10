"""Mail pushed to us as a signed JSON POST (`POST /inbound/webhook`), for providers and relays that forward
mail instead of exposing a mailbox. The signature is the Standard Webhooks scheme the outgoing webhook channel
uses, keyed with `INBOUND_WEBHOOK_SECRET`. The route lives in `app/api/inbound_routes.py`."""

import base64
import binascii
import hmac
import time

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.inbound.base import InboundMessage, InboundSource
from app.inbound.mime import normalize_id, parse_message
from app.inbound.registry import register_source
from app.notifications.providers.webhook import sign

TOLERANCE = 300  # seconds a signed timestamp stays valid, which bounds replays


class WebhookMail(BaseModel):
    """Either the whole message (`raw`, base64 RFC 822: the same parsing as IMAP) or its parts."""

    model_config = ConfigDict(extra="forbid")

    raw: str | None = Field(default=None, max_length=400_000)
    sender: str = Field(default="", alias="from", max_length=320)
    to: list[str] = Field(default_factory=list, max_length=20)
    text: str = Field(default="", max_length=100_000)
    message_id: str | None = Field(default=None, max_length=998)
    in_reply_to: str | None = Field(default=None, max_length=998)
    references: list[str] = Field(default_factory=list, max_length=50)

    def to_message(self, webhook_id: str) -> InboundMessage:
        if self.raw is not None:
            msg = parse_message(base64.b64decode(self.raw, validate=True))
        else:
            msg = InboundMessage(
                sender=self.sender.strip().lower(),
                recipients=[a.strip().lower() for a in self.to],
                text=self.text,
                message_id=normalize_id(self.message_id),
                in_reply_to=normalize_id(self.in_reply_to),
                references=[i for r in self.references if (i := normalize_id(r))],
            )
        # A retried delivery repeats the webhook-id, so it dedupes even when the mail carried no Message-ID.
        msg.message_id = msg.message_id or f"webhook-{webhook_id}"
        return msg


def verify(body: bytes, msg_id: str, timestamp: str, signatures: str) -> bool:
    """True when one of the space-separated `v1,<sig>` values matches and the timestamp is recent."""
    secret = settings.inbound_webhook_secret
    try:
        sent = int(timestamp)
        expected = sign(secret, msg_id, sent, body)
    except (ValueError, binascii.Error):
        return False
    if abs(time.time() - sent) > TOLERANCE:
        return False
    return any(hmac.compare_digest(expected, sig) for sig in signatures.split())


@register_source
class WebhookSource(InboundSource):
    key = "webhook"
    label = "Signed webhook"

    def is_configured(self) -> bool:
        return bool(settings.inbound_webhook_secret)
