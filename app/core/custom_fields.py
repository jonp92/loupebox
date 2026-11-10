"""Applying a site's custom fields to a submission's metadata."""

from app.schemas.custom_fields import TEXT_LIMIT


class MissingField(ValueError):
    """A required field has no usable answer. `.field` is its id."""

    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


def _answer(field: dict, value: object) -> str | bool | None:
    """What to store for `value`, or None to drop it (the widget may still hold a choice the site has since
    removed, and losing the answer is better than losing the feedback)."""
    if field["type"] == "checkbox":
        return value if isinstance(value, bool) else None
    if not isinstance(value, str):
        return None
    if field["type"] == "select":
        return value if value in {o["value"] for o in field["options"]} else None
    return value.strip()[: field["max_length"] or TEXT_LIMIT] or None


def apply_fields(fields: list[dict], metadata: dict) -> dict:
    """`metadata` with the site's fields checked: an answer that does not fit its field is dropped, a required
    field without one raises MissingField. Keys that are not fields pass through untouched."""
    out = dict(metadata)
    for field in fields:
        answer = _answer(field, out.pop(field["id"], None))
        # A required checkbox must be ticked, as the widget enforces.
        if field["required"] and (answer is None or answer is False):
            raise MissingField(field["id"])
        if answer is not None:
            out[field["id"]] = answer
    return out
