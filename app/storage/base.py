from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import ClassVar


class Storage(ABC):
    """Where attachment files live. Keys are server-made (`<site id>/<attachment id>`), never user input."""

    key: ClassVar[str]

    @abstractmethod
    def put(self, key: str, data: bytes) -> None:
        """Store the bytes under the key, replacing anything there. Readers never see half a file."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """The stored bytes. Raises FileNotFoundError when there are none."""

    @abstractmethod
    def delete(self, keys: Iterable[str]) -> None:
        """Remove the keys. Keys that are already gone are not an error."""

    @abstractmethod
    def entries(self) -> Iterator[tuple[str, datetime]]:
        """Every stored key with its last-modified time (UTC), for the orphan sweep."""
