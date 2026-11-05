from html import escape

from app.core.config import settings
from app.models import NotificationOutbox, Site
from app.notifications.base import Message
from app.notifications.layout import facts_table, quote, render

SUMMARY_EXCERPTS = 5
SUMMARY_EXCERPT_CHARS = 140


def _site_link(site: Site, feedback_id: str | None = None) -> str | None:
    base = settings.public_url.rstrip("/")
    if not base:
        return None
    return f"{base}/sites/{site.id}" + (f"/feedback/{feedback_id}" if feedback_id else "")


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _safe_href(url: str) -> str | None:
    return url if url.lower().startswith(("http://", "https://")) else None


def _event(row: NotificationOutbox, site: Site, type_: str, data: dict) -> dict:
    """The machine-readable form of an event. `id` is stable across retries, so receivers can dedupe."""
    return {
        "id": str(row.id),
        "type": type_,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "site": {"id": str(site.id), "name": _one_line(site.name)},
        "data": data,
    }


def build_message(row: NotificationOutbox, site: Site, recipients: list[str]) -> Message:
    p = row.payload
    link = _site_link(site, p.get("feedback_id"))
    facts = []
    if p.get("issue_type"):
        facts.append(("Type", p["issue_type"].replace("-", " ").replace("_", " ").capitalize()))
    if p.get("rating") is not None:
        facts.append(("Rating", str(p["rating"])))
    who = " ".join(x for x in (p.get("name"), p.get("email")) if x)
    if who:
        facts.append(("From", who))
    if p.get("page_url"):
        facts.append(("Page", p["page_url"]))

    text = "\n".join([p.get("excerpt", ""), "", *(f"{k}: {v}" for k, v in facts)] + ([link] if link else []))
    rows = [
        (
            k,
            f'<a class="lnk" href="{escape(v, quote=True)}" style="color:#007a94">{escape(v)}</a>'
            if k == "Page" and _safe_href(v)
            else escape(v),
        )
        for k, v in facts
    ]
    body = quote(escape(p.get("excerpt", "")).replace("\n", "<br>")) + (facts_table(rows) if rows else "")
    return Message(
        to=recipients,
        subject=f"New feedback on {_one_line(site.name)}",
        text=text.strip(),
        html=render(
            heading="New feedback",
            preheader=_one_line(p.get("excerpt", ""))[:120],
            body=body,
            link=link,
            site=_one_line(site.name),
        ),
        reply_to=p.get("email"),
        tags=[row.event_type],
        event=_event(row, site, row.event_type, {**{k: v for k, v in p.items() if k != "type"}, "url": link}),
    )


def build_summary(rows: list[NotificationOutbox], site: Site, recipients: list[str]) -> Message:
    """One email standing in for rows held back by the hourly cap."""
    link = _site_link(site)
    shown = rows[:SUMMARY_EXCERPTS]
    excerpts = [_one_line(r.payload.get("excerpt", ""))[:SUMMARY_EXCERPT_CHARS] for r in shown]
    n = len(rows)
    more = n - len(shown)

    head = f"{n} more feedback {'item' if n == 1 else 'items'} arrived on {_one_line(site.name)}."
    text = "\n".join([head, "", *(f"- {e}" for e in excerpts)] + ([f"...and {more} more"] if more else []))
    if link:
        text += f"\n\n{link}"
    items = "".join(f'<li style="margin:0 0 6px">{escape(e)}</li>' for e in excerpts)
    body = f'<p class="text" style="margin:12px 0 0;color:#0f1720;font-size:15px">{escape(head)}</p>' + quote(
        f'<ul style="margin:0;padding-left:18px">{items}</ul>'
        + (f'<div style="margin-top:8px;opacity:.7">...and {more} more</div>' if more else "")
    )
    return Message(
        to=recipients,
        subject=f"{n} more feedback on {_one_line(site.name)}",
        text=text,
        html=render(
            heading=f"{n} more feedback", preheader=head, body=body, link=link, site=_one_line(site.name)
        ),
        tags=["feedback.summary"],
        event=_event(rows[0], site, "feedback.summary", {"count": n, "excerpts": excerpts, "url": link}),
    )
