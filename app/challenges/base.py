from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models import Site


class ChallengeVerifier(ABC):
    """One way of making a public submission prove it cost something (proof-of-work, a CAPTCHA, ...).

    Subclass and use @register_verifier. A site picks one by name in `Site.challenge_mode`;
    "off" is reserved and never registered.
    """

    key: ClassVar[str]
    label: ClassVar[str]
    # Per-site settings, validated on save and before each use. Never put secrets here.
    ConfigModel: ClassVar[type[BaseModel]]

    @abstractmethod
    def issue(self, site: Site, config: BaseModel) -> dict[str, Any]:
        """What a client needs to produce a proof. Returned as JSON beside `mode`. Must not touch the DB."""

    @abstractmethod
    def verify(self, db: Session, site: Site, config: BaseModel, proof: str) -> bool:
        """True if `proof` (the opaque string sent with the submission) is valid and unused."""
