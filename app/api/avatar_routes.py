import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User

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
