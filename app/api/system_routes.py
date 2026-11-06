from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_superadmin
from app.core import health
from app.db.session import get_db

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_superadmin)])


@router.get("/health")
def instance_health(db: Session = Depends(get_db)) -> health.Health:
    return health.check(db)
