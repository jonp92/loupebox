from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_superadmin
from app.core import runtime_settings
from app.db.session import get_db
from app.models import User
from app.schemas.settings import SettingOut, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_superadmin)])


@router.get("")
def list_settings() -> list[SettingOut]:
    return [SettingOut(**s) for s in runtime_settings.describe()]


@router.patch("")
def update_settings(
    body: SettingsUpdate, db: Session = Depends(get_db), user: User = Depends(require_superadmin)
) -> list[SettingOut]:
    try:
        runtime_settings.save(db, user, body.changes)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return list_settings()
