import csv
import io
import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SiteAccess, feedback_or_404, site_access
from app.core.attachments import delete_files, keys_for
from app.core.audit import audit
from app.core.cache import menus
from app.core.config import settings
from app.core.events import publish
from app.core.feedback_query import (
    ISSUE_TYPE,
    TOTAL_CAP,
    Filters,
    assignable,
    capped_count,
    conditions,
    filters,
    issue_type_col,
    sort_by,
)
from app.db.session import get_db, get_sessionmaker
from app.models import (
    NOT_SPAM,
    Feedback,
    FeedbackNote,
    FeedbackTag,
    Membership,
    Role,
    User,
    user_matches,
    user_name,
)
from app.schemas.feedback import (
    MAX_TAGS,
    Assignee,
    BulkResult,
    FeedbackBulk,
    FeedbackOut,
    FeedbackPage,
    FeedbackUpdate,
    NoteIn,
    NoteOut,
    QuickCounts,
    TagCount,
)

router = APIRouter(prefix="/sites/{site_id}/feedback", tags=["feedback"])


def _check_assignee(db: Session, site_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is not None and db.scalar(assignable(site_id).where(User.id == user_id)) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Assignee must be an editor or admin of this site"
        )


def _set_tags(item: Feedback, tags: list[str]) -> None:
    item.tag_rows = [FeedbackTag(tag=t) for t in tags]


@router.get("")
def list_feedback(
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
    f: Filters = Depends(filters),
    order: tuple = Depends(sort_by),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> FeedbackPage:
    where = conditions(f, Feedback.site_id == access.site.id, site_fields=access.site.custom_fields)
    # Stop counting at the cap, or at the end of the page being viewed if that is further.
    total, capped = capped_count(db, where, max(TOTAL_CAP, offset + limit))
    rows = db.scalars(
        select(Feedback).where(*where).order_by(*order).limit(limit).offset(offset)
    )
    return FeedbackPage(items=[FeedbackOut.model_validate(r) for r in rows], total=total, total_capped=capped)


CSV_COLUMNS = (
    "id",
    "created_at",
    "status",
    "issue_type",
    "rating",
    "name",
    "email",
    "message",
    "page_url",
    "meta",
    "tags",
    "assignee",
)
# A spreadsheet treats a cell starting with one of these as a formula. Submitter text is untrusted.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: object) -> object:
    """Neutralise formula injection (OWASP "CSV injection"): text that would run as a formula is
    prefixed with an apostrophe, which spreadsheets show as plain text. Numbers pass through."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _issue_type_of(item: Feedback) -> str | None:
    value = (item.meta or {}).get("issue_type")
    return value if isinstance(value, str) and re.match(ISSUE_TYPE, value) else None


def _answer(item: Feedback, field_id: str) -> object:
    """A custom field's stored answer as a cell: a choice's value, true or false, or the text."""
    value = (item.meta or {}).get(field_id)
    return str(value).lower() if isinstance(value, bool) else value


def _csv_rows(site_id: uuid.UUID, where: list, fields: list[dict]) -> Iterator[str]:
    """Stream the file in batches, on its own session: the request's session may be closed by the time
    the response body is produced."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")

    def flush() -> str:
        text = buf.getvalue()
        buf.seek(0)
        buf.truncate()
        return text

    yield "\ufeff"  # byte-order mark so Excel reads the file as UTF-8
    # The site's own columns come last, so the fixed ones keep their positions.
    writer.writerow((*CSV_COLUMNS, *(csv_cell(f["label"]) for f in fields)))
    yield flush()
    with get_sessionmaker()() as db:
        emails = {
            uid: email
            for uid, email in db.execute(
                select(User.id, User.email).join(Membership).where(Membership.site_id == site_id)
            )
        }
        stmt = (
            select(Feedback)
            .where(*where)
            .order_by(Feedback.created_at.desc())
            .limit(settings.export_max_rows)
            .execution_options(yield_per=500)
        )
        for n, item in enumerate(db.scalars(stmt), 1):
            writer.writerow(
                csv_cell(v)
                for v in (
                    item.id,
                    item.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    item.status.value,
                    _issue_type_of(item),
                    item.rating,
                    item.name,
                    item.email,
                    item.message,
                    item.page_url,
                    json.dumps(item.meta, ensure_ascii=False, separators=(",", ":")) if item.meta else "",
                    " ".join(item.tags),
                    emails.get(item.assignee_id),
                    *(_answer(item, f["id"]) for f in fields),
                )
            )
            if n % 500 == 0:
                yield flush()
    yield flush()


@router.get("/issue-types")
def issue_types(
    access: SiteAccess = Depends(site_access(Role.viewer)), db: Session = Depends(get_db)
) -> list[dict]:
    """The issue types visitors have sent (from the widget's badges) with how many, for the list filter.
    Cached for 30 s: counting them reads the whole site."""

    def compute() -> list[dict]:
        rows = db.execute(
            select(issue_type_col, func.count())
            .where(
                Feedback.site_id == access.site.id,
                Feedback.status.in_(NOT_SPAM),
                issue_type_col.is_not(None),
            )
            .group_by(issue_type_col)
            .order_by(func.count().desc())
        )
        return [{"id": value, "count": count} for value, count in rows if re.match(ISSUE_TYPE, value or "")]

    return menus.get((access.site.id, "issue_types"), compute)


@router.get("/tags")
def tags(
    access: SiteAccess = Depends(site_access(Role.viewer)), db: Session = Depends(get_db)
) -> list[TagCount]:
    """The site's tags with how many items carry each, for the list filter and the tag picker.
    Cached for 30 s, and dropped when tags change here: counting them reads the whole site."""

    def compute() -> list[TagCount]:
        rows = db.execute(
            select(FeedbackTag.tag, func.count())
            .join(Feedback, Feedback.id == FeedbackTag.feedback_id)
            .where(Feedback.site_id == access.site.id)
            .group_by(FeedbackTag.tag)
            .order_by(func.count().desc(), FeedbackTag.tag)
        )
        return [TagCount(tag=tag, count=count) for tag, count in rows]

    return menus.get((access.site.id, "tags"), compute)


@router.get("/counts")
def counts(
    access: SiteAccess = Depends(site_access(Role.viewer)), db: Session = Depends(get_db)
) -> QuickCounts:
    """Sizes of the list's quick tabs: what is assigned to the caller and what is nobody's (spam excluded)."""

    def count(*extra) -> tuple[int, bool]:
        return capped_count(db, conditions(Filters(), Feedback.site_id == access.site.id, *extra), TOTAL_CAP)

    mine, mine_capped = count(Feedback.assignee_id == access.user.id)
    unassigned, unassigned_capped = count(Feedback.assignee_id.is_(None))
    return QuickCounts(
        mine=mine, mine_capped=mine_capped, unassigned=unassigned, unassigned_capped=unassigned_capped
    )


@router.get("/assignees")
def assignees(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=8, ge=1, le=20),
    access: SiteAccess = Depends(site_access(Role.editor)),
    db: Session = Depends(get_db),
) -> list[Assignee]:
    """The picker's search: editors and admins of the site whose name or email contains `q`. Never the whole
    member list, which can be long."""
    stmt = assignable(access.site.id)
    if q.strip():
        stmt = stmt.where(user_matches(q))
    rows = db.execute(
        stmt.with_only_columns(User.id, User.email, user_name()).order_by(User.email).limit(limit)
    )
    return [Assignee(user_id=uid, email=email, name=name) for uid, email, name in rows]


@router.get("/export.csv")
def export_feedback(
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
    f: Filters = Depends(filters),
) -> StreamingResponse:
    """The same filters as the list, as a CSV download (capped at `EXPORT_MAX_ROWS` rows)."""
    where = conditions(f, Feedback.site_id == access.site.id, site_fields=access.site.custom_fields)
    total = db.scalar(select(func.count()).select_from(Feedback).where(*where)) or 0
    audit(  # bulk personal data leaving the system; the contents are not recorded
        db,
        access.user,
        "feedback.export",
        f"Exported feedback from {access.site.name} as CSV",
        target_type="site",
        target_id=access.site.id,
        site=access.site,
        details={
            "rows": min(total, settings.export_max_rows),
            "status": f.status.value if f.status else None,
            "search": bool(f.q),
            "issue_type": f.issue_type,
            "rating": f.rating,
            "has_email": f.has_email,
            "from": str(f.created_from or ""),
            "to": str(f.created_to or ""),
            "assignee": f.assignee,
            "tag": f.tag,
            "fields": sorted(f.fields),  # which custom fields were filtered on, not the values
        },
    )
    db.commit()
    slug = re.sub(r"[^a-z0-9]+", "-", access.site.name.lower()).strip("-")[:40] or "site"
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return StreamingResponse(
        _csv_rows(access.site.id, where, access.site.custom_fields),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="feedback-{slug}-{day}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/bulk")
def bulk_feedback(
    body: FeedbackBulk,
    access: SiteAccess = Depends(site_access(Role.editor)),
    db: Session = Depends(get_db),
) -> BulkResult:
    """Change the status of, or delete, several items at once. Ids that are not in this site are
    skipped (not an error, and not revealed). Deleting needs the admin role, as for a single item."""
    if body.action == "delete":
        access.require(Role.admin)
    ids = set(body.ids)
    items = list(db.scalars(select(Feedback).where(Feedback.site_id == access.site.id, Feedback.id.in_(ids))))
    if body.action == "delete":
        audit(  # as for a single delete: ids and count only, never the messages
            db,
            access.user,
            "feedback.bulk_delete",
            f"Deleted {len(items)} feedback items from {access.site.name}",
            target_type="site",
            target_id=access.site.id,
            site=access.site,
            details={"count": len(items), "ids": sorted(str(i.id) for i in items)},
        )
        files = keys_for(db, Feedback.id.in_([i.id for i in items]))
        for item in items:
            db.delete(item)
    elif body.action == "set_status":
        for item in items:
            item.status = body.status
    elif body.action == "assign":
        _check_assignee(db, access.site.id, body.assignee_id)
        for item in items:
            item.assignee_id = body.assignee_id
        _audit_labels(
            db,
            access,
            "bulk_assign",
            f"Assigned {len(items)} feedback items on {access.site.name}",
            {"count": len(items), "assignee_id": _str(body.assignee_id), "ids": _ids(items)},
        )
    else:
        add = body.action == "add_tag"
        for item in items:
            if add and body.tag not in item.tags and len(item.tags) >= MAX_TAGS:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"An item can have at most {MAX_TAGS} tags"
                )
            _set_tags(item, sorted({*item.tags, body.tag} if add else set(item.tags) - {body.tag}))
        _audit_labels(
            db,
            access,
            body.action,
            f"{'Added' if add else 'Removed'} tag {body.tag} on {len(items)} feedback items"
            f" in {access.site.name}",
            {"count": len(items), "tag": body.tag, "ids": _ids(items)},
        )
    publish(db, "feedback", access.site.id)
    db.commit()
    if body.action == "delete":
        delete_files(files)
    menus.invalidate(access.site.id)
    return BulkResult(affected=len(items), skipped=len(ids) - len(items))


def _str(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def _ids(items: list[Feedback]) -> list[str]:
    return sorted(str(i.id) for i in items)


def _audit_labels(db: Session, access: SiteAccess, action: str, summary: str, details: dict) -> None:
    """Assignment and tag changes: who and what, never the feedback text. (Status changes are not logged.)"""
    audit(
        db,
        access.user,
        f"feedback.{action}",
        summary,
        target_type="site",
        target_id=access.site.id,
        site=access.site,
        details=details,
    )


@router.get("/{feedback_id}")
def get_feedback(
    feedback_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    return FeedbackOut.model_validate(feedback_or_404(db, access.site.id, feedback_id))


@router.patch("/{feedback_id}")
def update_feedback(
    feedback_id: uuid.UUID,
    body: FeedbackUpdate,
    access: SiteAccess = Depends(site_access(Role.editor)),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    item = feedback_or_404(db, access.site.id, feedback_id)
    sent = body.model_fields_set
    if "status" in sent:
        item.status = body.status
    if "assignee_id" in sent:
        _check_assignee(db, access.site.id, body.assignee_id)
        if item.assignee_id != body.assignee_id:
            item.assignee_id = body.assignee_id
            _audit_labels(
                db,
                access,
                "assign",
                f"Assigned a feedback item on {access.site.name}",
                {"feedback_id": str(item.id), "assignee_id": _str(body.assignee_id)},
            )
    if "tags" in sent and body.tags != item.tags:
        _audit_labels(
            db,
            access,
            "tags",
            f"Changed the tags of a feedback item on {access.site.name}",
            {"feedback_id": str(item.id), "from": item.tags, "to": body.tags},
        )
        _set_tags(item, body.tags)
    publish(db, "feedback", access.site.id, item.id)
    db.commit()
    menus.invalidate(access.site.id)
    return FeedbackOut.model_validate(item)


@router.get("/{feedback_id}/notes")
def list_notes(
    feedback_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.viewer)),
    db: Session = Depends(get_db),
) -> list[NoteOut]:
    item = feedback_or_404(db, access.site.id, feedback_id)
    rows = db.execute(
        select(FeedbackNote, user_name())
        .outerjoin(User, User.id == FeedbackNote.author_id)
        .where(FeedbackNote.feedback_id == item.id)
        .order_by(FeedbackNote.created_at)
    )
    return [NoteOut.model_validate(n).model_copy(update={"author_name": name}) for n, name in rows]


@router.post("/{feedback_id}/notes", status_code=status.HTTP_201_CREATED)
def add_note(
    feedback_id: uuid.UUID,
    body: NoteIn,
    access: SiteAccess = Depends(site_access(Role.editor)),
    db: Session = Depends(get_db),
) -> NoteOut:
    item = feedback_or_404(db, access.site.id, feedback_id)
    note = FeedbackNote(feedback_id=item.id, author_id=access.user.id, body=body.body)
    db.add(note)
    publish(db, "thread", access.site.id, item.id)
    db.commit()
    return NoteOut.model_validate(note).model_copy(
        update={"author_name": db.scalar(select(user_name()).where(User.id == access.user.id))}
    )


@router.delete("/{feedback_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    feedback_id: uuid.UUID,
    note_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.editor)),
    db: Session = Depends(get_db),
) -> None:
    """An editor removes their own notes; an admin can remove any."""
    item = feedback_or_404(db, access.site.id, feedback_id)
    note = db.scalar(
        select(FeedbackNote).where(FeedbackNote.id == note_id, FeedbackNote.feedback_id == item.id)
    )
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    if note.author_id != access.user.id and not access.has(Role.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the author or an admin can delete a note")
    audit(
        db,
        access.user,
        "feedback.note_delete",
        f"Deleted a note on a feedback item in {access.site.name}",
        target_type="feedback",
        target_id=item.id,
        site=access.site,
        details={"note_id": str(note.id)},
    )
    db.delete(note)
    publish(db, "thread", access.site.id, feedback_id)
    db.commit()


@router.delete("/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback(
    feedback_id: uuid.UUID,
    access: SiteAccess = Depends(site_access(Role.admin)),
    db: Session = Depends(get_db),
) -> None:
    item = feedback_or_404(db, access.site.id, feedback_id)
    audit(  # the message itself is personal data, so only its id and status are kept
        db,
        access.user,
        "feedback.delete",
        f"Deleted a feedback item from {access.site.name}",
        target_type="feedback",
        target_id=item.id,
        site=access.site,
        details={"status": item.status.value},
    )
    files = keys_for(db, Feedback.id == item.id)
    db.delete(item)
    publish(db, "feedback", access.site.id, item.id)
    db.commit()
    delete_files(files)
    menus.invalidate(access.site.id)
