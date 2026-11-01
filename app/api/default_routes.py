from fastapi import APIRouter

from app.core.config import settings
from app.schemas import HealthResponse, VersionResponse

router = APIRouter()


@router.get("/health")
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/version")
def version_check() -> VersionResponse:
    return VersionResponse(
        app_name=settings.app_name,
        app_version=settings.app_version,
        app_description=settings.app_description,
    )