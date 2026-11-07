from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_configured, require_superadmin
from app.core import health
from app.core.attachments import move_images, storage_counts
from app.core.audit import audit
from app.core.config import settings
from app.core.rate_limit import enforce
from app.db.session import get_db
from app.models import User
from app.notifications.registry import get_provider
from app.notifications.system_mail import send_system_email, test_message
from app.schemas.notification import TestResult
from app.schemas.storage import MoveResult, StorageStatus, StorageTest
from app.storage.base import StorageError
from app.storage.registry import get_storage

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_superadmin)])

TEST_LIMIT, TEST_WINDOW = 5, 600  # test emails per superadmin per 10 minutes
MOVE_BATCH = 10  # image files moved per request; the admin page asks again until none are left


class TestEmail(BaseModel):
    __test__ = False  # not a pytest class

    provider: str


@router.get("/health")
def instance_health(db: Session = Depends(get_db)) -> health.Health:
    return health.check(db)


@router.post("/test-email")
def send_test_email(body: TestEmail, user: User = Depends(require_superadmin)) -> TestResult:
    """Send one email through the chosen provider to the caller only. Not queued, not stored."""
    provider = get_provider(body.provider)
    if provider is None or not provider.uses_recipients:
        raise HTTPException(422, f"Not an email provider: {body.provider}")
    require_configured(provider)
    enforce(f"mail-test:{user.id}", TEST_LIMIT, TEST_WINDOW)
    subject, text, html = test_message(provider.label)
    result = send_system_email(user.email, subject, text, html, "test", provider=provider)
    return TestResult(status=result.status, error=result.error, to=user.email)


@router.get("/storage")
def storage_status(db: Session = Depends(get_db)) -> StorageStatus:
    counts = storage_counts(db)
    current = settings.storage_backend
    return StorageStatus(
        backend=current,
        configured=get_storage().is_configured(),
        counts=counts,
        to_move=sum(n for name, n in counts.items() if name != current),
    )


@router.post("/test-storage")
def test_storage(user: User = Depends(require_superadmin)) -> StorageTest:
    """Write, read back and delete a probe file in the current storage; say what is wrong if it fails."""
    enforce(f"storage-test:{user.id}", TEST_LIMIT * 2, TEST_WINDOW)
    storage = get_storage()
    try:
        storage.check()
    except StorageError as e:
        return StorageTest(status="failed", backend=storage.key, error=str(e))
    return StorageTest(status="ok", backend=storage.key)


@router.post("/storage/move")
def move_storage(user: User = Depends(require_superadmin), db: Session = Depends(get_db)) -> MoveResult:
    """Move the next few image files into the current storage. Called again until `remaining` is 0."""
    storage = get_storage()
    if not storage.is_configured():
        raise HTTPException(409, "The current storage is not set up yet")
    result = move_images(db, storage.key, MOVE_BATCH)
    if result.moved or result.missing or result.failed:
        audit(
            db,
            user,
            "storage.move",
            f"Moved {result.moved} image files to {storage.key} storage",
            target_type="settings",
            target_id="storage",
            details={
                "to": storage.key,
                "moved": result.moved,
                "missing": result.missing,
                "failed": result.failed,
            },
        )
        db.commit()
    return MoveResult(
        moved=result.moved,
        missing=result.missing,
        failed=result.failed,
        remaining=result.remaining,
        error=result.error or None,
    )
