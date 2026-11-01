from fastapi import FastAPI

from app.api import (
    auth_routes,
    avatar_routes,
    default_routes,
    feedback_routes,
    public_routes,
    site_routes,
    stats_routes,
    user_routes,
)
from app.core.config import settings
from app.core.middleware import BodySizeLimitMiddleware, DynamicCORSMiddleware

app = FastAPI(title=settings.app_name)

# Added first = innermost, so 413s from the size limit still get CORS headers.
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=settings.max_body_bytes,
    overrides={"/auth/me/avatar": settings.avatar_max_bytes + 1024},
)
app.add_middleware(DynamicCORSMiddleware)

app.include_router(default_routes.router)
app.include_router(public_routes.router)
app.include_router(auth_routes.router)
app.include_router(avatar_routes.router)
app.include_router(user_routes.router)
app.include_router(site_routes.router)
app.include_router(feedback_routes.router)
app.include_router(stats_routes.router)
