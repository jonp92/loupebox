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

    def is_configured(self) -> bool:
        """True when the server-side settings this provider needs (API keys, ...) are present."""
        return True

    @abstractmethod
    def send(self, message: Message, config: BaseModel) -> SendResult:
        """Deliver one message. Return a result instead of raising for expected failures."""
