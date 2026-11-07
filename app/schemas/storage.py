from typing import Literal

from pydantic import BaseModel


class StorageStatus(BaseModel):
    backend: str  # where new images go
    configured: bool
    counts: dict[str, int]  # image files held by each backend
    to_move: int  # files that are not in the current backend


class StorageTest(BaseModel):
    status: Literal["ok", "failed"]
    backend: str
    error: str | None = None


class MoveResult(BaseModel):
    moved: int
    missing: int
    failed: int
    remaining: int
    error: str | None = None
