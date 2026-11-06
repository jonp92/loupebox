from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow

_JSON = JSON().with_variant(JSONB(), "postgresql")


class AppSetting(Base):
    """A superadmin's override of one env setting (see app/core/runtime_settings.py).

    Secrets are stored as a Fernet token, never in the clear. The editor is a snapshot (no foreign key),
    like the audit log.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(_JSON)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(320))
