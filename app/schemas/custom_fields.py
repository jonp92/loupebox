"""A site's custom fields: what its feedback form asks besides the message.

The definitions live on the site (`Site.custom_fields`); a visitor's answers are stored in the feedback's
`meta` under each field's id. A select's stored value is language-independent: translations only change what
the visitor and the admin UI read, never what is saved, so filters and exports do not split by language.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import clean_text

FIELD_ID = r"^[a-z0-9][a-z0-9_-]{0,31}$"  # the same slugs the widget accepts for its own extra fields
LOCALE = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$"  # "de", "pt-BR", "zh-Hant-TW"
RESERVED_IDS = frozenset({"issue_type", "widget_version", "locale"})  # keys the widget sets itself
MAX_FIELDS = 10
MAX_OPTIONS = 20
MAX_LOCALES = 8  # per site, across all fields
MAX_IN_LIST = 2  # fields that also show as badges on feedback rows
TEXT_LIMIT = 256  # also the most the ingest keeps of any metadata string


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _text(v: str) -> str:
    v = clean_text(v)
    if not v:
        raise ValueError("must not be blank")
    return v


class FieldOption(_Strict):
    value: str = Field(max_length=64)  # what is stored
    label: str = Field(max_length=64)  # what a visitor reads, in the site's own language

    @field_validator("value", "label")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _text(v)


class FieldTranslation(_Strict):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    options: dict[str, str] = Field(default_factory=dict, max_length=MAX_OPTIONS)  # option value -> label

    @field_validator("options")
    @classmethod
    def _options(cls, v: dict[str, str]) -> dict[str, str]:
        if any(not 1 <= len(label) <= 64 for label in v.values()):
            raise ValueError("option labels must be 1 to 64 characters")
        return v


class CustomField(_Strict):
    id: str = Field(pattern=FIELD_ID)
    type: Literal["select", "checkbox", "text"]
    label: str = Field(min_length=1, max_length=80)
    required: bool = False
    options: list[FieldOption] = Field(default_factory=list, max_length=MAX_OPTIONS)  # select only
    max_length: int | None = Field(default=None, ge=1, le=TEXT_LIMIT)  # text only
    show_in_list: bool = False
    translations: dict[str, FieldTranslation] = Field(default_factory=dict, max_length=MAX_LOCALES)

    @field_validator("label")
    @classmethod
    def _clean_label(cls, v: str) -> str:
        return _text(v)

    @field_validator("translations")
    @classmethod
    def _locales(cls, v: dict[str, FieldTranslation]) -> dict[str, FieldTranslation]:
        for code in v:
            if not re.match(LOCALE, code):
                raise ValueError(f"{code!r} is not a language code such as 'de' or 'pt-BR'")
        return v

    @model_validator(mode="after")
    def _shape(self) -> "CustomField":
        if self.id in RESERVED_IDS:
            raise ValueError(f"the id {self.id!r} is reserved")
        values = [o.value for o in self.options]
        if self.type == "select":
            if not values:
                raise ValueError("a select needs at least one option")
            if len(set(values)) != len(values):
                raise ValueError("option values must be unique")
        elif self.options:
            raise ValueError("only a select has options")
        if self.max_length is not None and self.type != "text":
            raise ValueError("only a text field has a max_length")
        for code, tr in self.translations.items():
            unknown = set(tr.options) - set(values)
            if unknown:
                raise ValueError(
                    f"{code}: translated options that do not exist: {', '.join(sorted(unknown))}"
                )
        return self


class CustomFields(BaseModel):
    """The whole list, validated together: limits and uniqueness span fields."""

    fields: list[CustomField] = Field(max_length=MAX_FIELDS)

    @model_validator(mode="after")
    def _across(self) -> "CustomFields":
        ids = [f.id for f in self.fields]
        if len(set(ids)) != len(ids):
            raise ValueError("field ids must be unique")
        if sum(f.show_in_list for f in self.fields) > MAX_IN_LIST:
            raise ValueError(f"at most {MAX_IN_LIST} fields can show in the list")
        if len({code for f in self.fields for code in f.translations}) > MAX_LOCALES:
            raise ValueError(f"at most {MAX_LOCALES} languages per site")
        return self


def validate_fields(raw: list[dict]) -> list[dict]:
    """The list as stored: validated, with defaults filled in. Raises pydantic's ValidationError."""
    return CustomFields(fields=raw).model_dump()["fields"]
