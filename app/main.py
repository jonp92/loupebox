import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.concurrency import run_in_threadpool

from app.api import (
    attachment_routes,
    audit_routes,
    auth_routes,
    avatar_routes,
    dashboard_routes,
    default_routes,
    event_routes,
    feedback_routes,
    inbox_routes,
    notification_routes,
    password_reset_routes,
    privacy_routes,
    public_routes,
    reply_routes,
    settings_routes,
    site_routes,
    stats_routes,
    system_routes,
    user_routes,
)
from app.challenges.registry import load_verifiers
from app.core import events, runtime_settings
from app.core.config import settings
from app.core.middleware import BodySizeLimitMiddleware, ConcurrencyLimitMiddleware, DynamicCORSMiddleware
from app.db.session import get_sessionmaker
from app.notifications.registry import load_providers

prefix = settings.api_prefix
load_providers()  # the admin API lists providers and sends test messages
load_verifiers()  # public ingest enforces each site's challenge mode


SETTINGS_RELOAD_SECONDS = 30
log = logging.getLogger("loupebox.settings")


def _load_settings() -> None:
    with get_sessionmaker()() as db:
        runtime_settings.load(db)  # settings saved in the admin UI win over env


async def _reload_settings() -> None:
    """Pick up settings saved through another API replica (this one applies its own saves at once)."""
    while True:
        await asyncio.sleep(SETTINGS_RELOAD_SECONDS)
        try:
            await run_in_threadpool(_load_settings)
        except Exception:
            log.exception("reloading saved settings failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _load_settings()
    reload = asyncio.create_task(_reload_settings())
    stop_events = events.start_listener()
    yield
    reload.cancel()
    if stop_events:
        stop_events.set()


# Interactive docs only outside production, so a deployed instance doesn't advertise its schema.
_docs = settings.environment != "production"
app = FastAPI(
    title=settings.app_name,
    docs_url=f"{prefix}/docs" if _docs else None,
    redoc_url=f"{prefix}/redoc" if _docs else None,
    openapi_url=f"{prefix}/openapi.json" if _docs else None,
    lifespan=lifespan,
)

# Added first = innermost, so 413s and 503s still get CORS headers, and oversized bodies never take a slot.
app.add_middleware(
    ConcurrencyLimitMiddleware,
    limit=settings.max_concurrent_requests or settings.db_pool_size + settings.db_max_overflow,
    wait_seconds=settings.request_queue_seconds,
    exempt=frozenset({f"{prefix}/health", f"{prefix}/events"}),  # a stream would hold its slot for hours
)
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=settings.max_body_bytes,
    overrides={
        "/avatar": settings.avatar_max_bytes + 1024,
        "/feedback/with-images": settings.attachment_request_bytes,
    },
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
    inbox_routes,
    attachment_routes,
    privacy_routes,
    reply_routes,
    notification_routes,
    stats_routes,
    dashboard_routes,
    event_routes,
    settings_routes,
    system_routes,
):
    api.include_router(module.router)
app.include_router(api)
