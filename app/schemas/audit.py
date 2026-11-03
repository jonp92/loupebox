import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor_id: uuid.UUID | None
    actor_email: str
    action: str
    target_type: str
    target_id: str
    site_id: uuid.UUID | None
    site_name: str | None
    summary: str
    details: dict[str, Any]


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
