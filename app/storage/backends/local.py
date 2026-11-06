"""Files on a local disk, under ATTACHMENTS_DIR. One host, or one volume shared by the API and the worker."""

import os
import re
import uuid
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.storage.base import Storage
from app.storage.registry import register_backend

# Slash-separated names of letters, digits, "-" and "_": no dots and no empty parts, so a key can't climb out.
_KEY = re.compile(r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$")
_TMP = "_tmp"  # unfinished writes live here, and are listed (and swept) like any other key


@register_backend
class LocalStorage(Storage):
    key = "local"

    def __init__(self) -> None:
        self.root = Path(settings.attachments_dir).resolve()

    def _path(self, key: str) -> Path:
        if not _KEY.match(key):
            raise ValueError("invalid storage key")
        return self.root / key

    def put(self, key: str, data: bytes) -> None:
        target = self._path(key)
        temp = self._path(f"{_TMP}/{uuid.uuid4().hex}")
        for path in (target, temp):
            path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(data)
        os.replace(temp, target)  # atomic on one filesystem

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, keys: Iterable[str]) -> None:
        for key in keys:
            self._path(key).unlink(missing_ok=True)

    def entries(self) -> Iterator[tuple[str, datetime]]:
        for path in self.root.rglob("*") if self.root.exists() else ():
            if path.is_file():
                yield (
                    path.relative_to(self.root).as_posix(),
                    datetime.fromtimestamp(path.stat().st_mtime, UTC),
                )
