import re
from typing import Literal

from pydantic import BaseModel

from app.models import Feedback

EXCERPT_CHARS = 500


ISSUE_TYPE = re.compile(r"^[a-z0-9_-]{1,32}$")


def issue_type_of(item: Feedback) -> str | None:
    """Client-supplied, so only a plain id gets into emails and webhooks."""
    value = (item.meta or {}).get("issue_type")
    return value if isinstance(value, str) and ISSUE_TYPE.match(value) else None


class FeedbackCreated(BaseModel):
    """Snapshot stored in the outbox, so a notification can render after the feedback is deleted."""

    type: Literal["feedback.created"] = "feedback.created"
    feedback_id: str
    excerpt: str
    rating: int | None = None
    name: str | None = None
    email: str | None = None
    page_url: str | None = None
    issue_type: str | None = None  # the widget's badge, when the visitor picked one

    @classmethod
    def from_feedback(cls, item: Feedback) -> "FeedbackCreated":
        return cls(
            feedback_id=str(item.id),
            excerpt=item.message[:EXCERPT_CHARS],
            rating=item.rating,
            name=item.name,
            email=item.email,
            page_url=item.page_url,
            issue_type=issue_type_of(item),
        )


class FeedbackReplied(BaseModel):
    """A reply was emailed to the submitter. Ids and length only: the reply text is not kept in the outbox."""

    type: Literal["feedback.replied"] = "feedback.replied"
    feedback_id: str
    reply_id: str
    length: int


EVENT_TYPES: dict[str, type[BaseModel]] = {
    "feedback.created": FeedbackCreated,
    "feedback.replied": FeedbackReplied,
}
# Only for endpoints that feed other systems (webhooks); emailing the team about its own replies is noise.
MACHINE_ONLY = {"feedback.replied"}
