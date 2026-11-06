from typing import Any, Literal

from pydantic import BaseModel


class SettingOut(BaseModel):
    key: str
    group: str
    label: str
    help: str
    type: Literal["integer", "string", "boolean", "list"]
    minimum: int | None
    maximum: int | None
    choices: list[str] | None
    secret: bool
    editable: bool
    source: Literal["default", "env", "ui"]
    configured: bool
    # Secrets: always None, the API never returns them.
    value: Any
    env_value: Any
    default: Any


class SettingsUpdate(BaseModel):
    # key -> new value, or None to drop the override and go back to the env value.
    changes: dict[str, Any]
