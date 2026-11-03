from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from pydantic import BaseModel


@dataclass
class Message:
    to: list[str]
    subject: str
    text: str
    html: str | None = None
    reply_to: str | None = None
    tags: list[str] = field(default_factory=list)
    # Structured form of the same event (type, id, site, data) for machine consumers like webhooks.
    event: dict | None = None
    # The channel's signing secret, filled in by the sender for providers with `signs = True`.
    secret: str | None = None


@dataclass
class SendResult:
    status: Literal["sent", "retry", "failed"]
    message_id: str | None = None
    error: str | None = None

    @classmethod
    def sent(cls, message_id: str | None = None) -> "SendResult":
        return cls("sent", message_id=message_id)

    @classmethod
    def retry(cls, error: str) -> "SendResult":
        return cls("retry", error=error)

    @classmethod
    def failed(cls, error: str) -> "SendResult":
        return cls("failed", error=error)


class NotificationProvider(ABC):
    """One delivery channel type (email via Brevo, Slack, ...). Subclass and use @register_provider."""

    key: ClassVar[str]
    label: ClassVar[str]
    # Per-channel settings, validated on save and before each send. Never put secrets here.
    ConfigModel: ClassVar[type[BaseModel]]
    # Email-like providers go to people (members plus extra addresses); others go to one endpoint.
    uses_recipients: ClassVar[bool] = True
    # Subject to the per-channel hourly cap and summary roll-up. Machine consumers want every event.
    rate_capped: ClassVar[bool] = True
    # Channels get a generated signing secret, shown once and stored encrypted.
    signs: ClassVar[bool] = False

    def is_configured(self) -> bool:
        """True when the server-side settings this provider needs (API keys, ...) are present."""
        return True

    def new_secret(self) -> str:
        """A fresh signing secret. Only called for providers with `signs = True`."""
        raise NotImplementedError

    def check_config(self, config: BaseModel) -> None:
        """Extra checks when a channel is saved (may do I/O). Raise ValueError with a user-facing reason."""

    @abstractmethod
    def send(self, message: Message, config: BaseModel) -> SendResult:
        """Deliver one message. Return a result instead of raising for expected failures."""
