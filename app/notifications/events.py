from typing import Literal

from pydantic import BaseModel

from app.models import Feedback

EXCERPT_CHARS = 500


class FeedbackCreated(BaseModel):
    """Snapshot stored in the outbox, so a notification can render after the feedback is deleted."""

    type: Literal["feedback.created"] = "feedback.created"
    feedback_id: str
    excerpt: str
    rating: int | None = None
    name: str | None = None
    email: str | None = None
    page_url: str | None = None

    @classmethod
    def from_feedback(cls, item: Feedback) -> "FeedbackCreated":
        return cls(
            feedback_id=str(item.id),
            excerpt=item.message[:EXCERPT_CHARS],
            rating=item.rating,
            name=item.name,
            email=item.email,
            page_url=item.page_url,
        )


EVENT_TYPES: dict[str, type[BaseModel]] = {"feedback.created": FeedbackCreated}
