from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_configured, require_superadmin
from app.core import health
from app.core.rate_limit import enforce
from app.db.session import get_db
from app.models import User
from app.notifications.registry import get_provider
from app.notifications.system_mail import send_system_email, test_message
from app.schemas.notification import TestResult

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_superadmin)])

TEST_LIMIT, TEST_WINDOW = 5, 600  # test emails per superadmin per 10 minutes


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
