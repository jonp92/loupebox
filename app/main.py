from fastapi import APIRouter, FastAPI

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

prefix = settings.api_prefix

# Interactive docs only outside production, so a deployed instance doesn't advertise its schema.
_docs = settings.environment != "production"
app = FastAPI(
    title=settings.app_name,
    docs_url=f"{prefix}/docs" if _docs else None,
    redoc_url=f"{prefix}/redoc" if _docs else None,
    openapi_url=f"{prefix}/openapi.json" if _docs else None,
)

# Added first = innermost, so 413s from the size limit still get CORS headers.
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=settings.max_body_bytes,
    overrides={f"{prefix}/auth/me/avatar": settings.avatar_max_bytes + 1024},
)
app.add_middleware(DynamicCORSMiddleware)

api = APIRouter(prefix=prefix)
for module in (
    default_routes,
    public_routes,
    auth_routes,
    avatar_routes,
    user_routes,
    site_routes,
    feedback_routes,
    stats_routes,
):
    api.include_router(module.router)
app.include_router(api)
