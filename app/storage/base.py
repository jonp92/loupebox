import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import ClassVar

# Slash-separated names of letters, digits, "-" and "_": no dots and no empty parts, so a key can't climb out
# of a folder or name something unexpected in a bucket. Keys are made by the server, never taken from users.
_KEY = re.compile(r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$")


def valid_key(key: str) -> str:
    if not _KEY.match(key):
        raise ValueError("invalid storage key")
    return key


class StorageError(Exception):
    """A problem with the storage itself. The message is written for the person setting it up."""


class Storage(ABC):
    """Where attachment files live. Keys are server-made (`<site id>/<attachment id>`), never user input."""

    key: ClassVar[str]

    def is_configured(self) -> bool:
        """False while something needed (a bucket, a key) is still missing."""
        return True

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
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

    def explain(self, error: Exception) -> str:
        """What a failure means, in words for the person setting up storage. Never includes secrets."""
        return f"{type(error).__name__}: {error}"[:200]

    def check(self) -> None:
        """Write, read back and delete a small probe file. Raises StorageError saying what is wrong."""
        if not self.is_configured():
            raise StorageError("Storage is not fully set up yet.")
        key, payload = f"_check/{uuid.uuid4().hex}", uuid.uuid4().bytes
        try:
            self.put(key, payload)
            if self.get(key) != payload:
                raise StorageError("What was read back is not what was written.")
            self.delete([key])
        except StorageError:
            raise
        except Exception as e:  # noqa: BLE001  (whatever went wrong is explained to the person setting up)
            raise StorageError(self.explain(e)) from None
