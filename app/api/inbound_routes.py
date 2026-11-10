import binascii
from collections import Counter

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core import health
from app.db.session import get_db
from app.inbound.ingest import ingest
from app.inbound.registry import get_source, load_sources
from app.inbound.sources.webhook import WebhookMail, verify
from app.models.user import utcnow

router = APIRouter(prefix="/inbound", tags=["inbound"])


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def receive(
    request: Request,
    db: Session = Depends(get_db),
    webhook_id: str = Header("", max_length=128),
    webhook_timestamp: str = Header("", max_length=20),
    webhook_signature: str = Header("", max_length=1024),
) -> Response:
    """Take one signed mail. The answer never says whether it matched a conversation, so the endpoint cannot
    be used to probe feedback ids or addresses. The body is size-limited in `app/main.py`."""
    load_sources()
    source = get_source("webhook")
    if not (source and source.is_configured()):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    body = await request.body()
    if not (webhook_id and verify(body, webhook_id, webhook_timestamp, webhook_signature)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")
    try:
        mail = WebhookMail.model_validate_json(body)
        message = mail.to_message(webhook_id)
    except (ValidationError, binascii.Error) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unreadable message") from exc
    outcome = ingest(db, message)
    db.commit()
    health.record_poll(db, source.key, utcnow(), outcomes=Counter({outcome: 1}))
    return Response(status_code=status.HTTP_202_ACCEPTED)
