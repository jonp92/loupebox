import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.schemas.common import sniff_image

router = APIRouter(tags=["avatars"])


@router.get("/avatars/{user_id}")
def get_avatar(user_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    """Serve a user's avatar image.

    Unauthenticated on purpose so a plain <img src> works. Ids are random UUIDs and the avatar is
    the only thing exposed. The `?v=` query in `avatar_url` changes on upload, so responses can be
    cached forever.
    """
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.avatar_data or not user.avatar_type or not user.is_active:
        raise HTTPException(404, "No avatar")
    return Response(
        content=user.avatar_data,
        media_type=user.avatar_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )


async def raw_body(request: Request) -> bytes:
    return await request.body()


def store_avatar(user: User, raw: bytes, content_type: str | None) -> None:
    """Validate a raw image upload and set it as the user's avatar. The caller commits."""
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Avatar must be PNG, JPEG or WebP")
    if len(raw) > settings.avatar_max_bytes:
        raise HTTPException(413, f"Avatar must be at most {settings.avatar_max_bytes // 1024} KB")
    if sniff_image(raw) != declared:
        raise HTTPException(422, "Image contents do not match its content type")
    user.avatar_data = raw
    user.avatar_type = declared
    user.avatar_updated_at = datetime.now(UTC)


def clear_avatar(user: User) -> None:
    user.avatar_data = user.avatar_type = user.avatar_updated_at = None
