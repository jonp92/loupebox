import enum
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from sqlalchemy.orm import Session


class Outcome(str, enum.Enum):
    stored = "stored"  # a customer reply was added to the conversation
    bounced = "bounced"  # an outbound reply was marked failed
    ignored = "ignored"  # a robot, an empty message or spam
    unmatched = "unmatched"  # no feedback item, or the sender is not the person who wrote it
    duplicate = "duplicate"  # already stored (the same Message-ID)


@dataclass
class InboundMessage:
    """One email reduced to what matching and storing need. Every source builds this; none of it is logged."""

    sender: str
    recipients: list[str]
    text: str
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    # reply: a person's answer. auto: out-of-office and other robots. bounce: a delivery failure notice.
    kind: Literal["reply", "auto", "bounce"] = "reply"
    # Bounces only: the Message-ID of the mail that failed, and the status code (such as 5.1.1).
    bounced_message_id: str | None = None
    bounce_code: str | None = None


class InboundSource(ABC):
    """One way mail reaches Loupebox (an IMAP mailbox, a webhook, ...). Subclass and use @register_source.

    Every source hands `InboundMessage`s to `app.inbound.ingest.ingest`, which does the matching and storing.
    """

    key: ClassVar[str]
    label: ClassVar[str]

    @abstractmethod
    def is_configured(self) -> bool:
        """True when the server settings this source needs are present."""


class PollingSource(InboundSource):
    """A source the worker asks for mail on a timer. Push sources (webhooks) have their own route instead."""

    @abstractmethod
    def poll(self, db: Session) -> Counter[Outcome]:
        """Fetch and ingest what is waiting; commit per message. Returns how each message turned out."""
