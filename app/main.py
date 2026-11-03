from fastapi import APIRouter, FastAPI

from app.api import (
    audit_routes,
    auth_routes,
    avatar_routes,
    dashboard_routes,
    default_routes,
    feedback_routes,
    notification_routes,
    password_reset_routes,
    public_routes,
    site_routes,
    stats_routes,
    user_routes,
)
from app.challenges.registry import load_verifiers
from app.core.config import settings
from app.core.middleware import BodySizeLimitMiddleware, DynamicCORSMiddleware
from app.notifications.registry import load_providers

prefix = settings.api_prefix
load_providers()  # the admin API lists providers and sends test messages
load_verifiers()  # public ingest enforces each site's challenge mode

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
    overrides={"/avatar": settings.avatar_max_bytes + 1024},
)
app.add_middleware(DynamicCORSMiddleware)

api = APIRouter(prefix=prefix)
for module in (
    default_routes,
    public_routes,
    auth_routes,
    audit_routes,
    avatar_routes,
    password_reset_routes,
    user_routes,
    site_routes,
    feedback_routes,
    notification_routes,
    stats_routes,
    dashboard_routes,
):
    api.include_router(module.router)
app.include_router(api)
