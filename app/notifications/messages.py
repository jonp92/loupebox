from html import escape

from app.core.config import settings
from app.models import NotificationOutbox, Site
from app.notifications.base import Message

SUMMARY_EXCERPTS = 5
SUMMARY_EXCERPT_CHARS = 140


def _site_link(site: Site) -> str | None:
    base = settings.public_url.rstrip("/")
    return f"{base}/sites/{site.id}" if base else None


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _html(paragraphs: list[str], link: str | None) -> str:
    """Every user-supplied string goes through escape(); `paragraphs` are already-escaped HTML."""
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    if link:
        body += f'<p><a href="{escape(link, quote=True)}">Open in Ganymede</a></p>'
    return f"<!doctype html><html><body>{body}</body></html>"


def build_message(row: NotificationOutbox, site: Site, recipients: list[str]) -> Message:
    p = row.payload
    link = _site_link(site)
    facts = []
    if p.get("rating") is not None:
        facts.append(("Rating", str(p["rating"])))
    who = " ".join(x for x in (p.get("name"), p.get("email")) if x)
    if who:
        facts.append(("From", who))
    if p.get("page_url"):
        facts.append(("Page", p["page_url"]))

    text = "\n".join([p.get("excerpt", ""), "", *(f"{k}: {v}" for k, v in facts)] + ([link] if link else []))
    paragraphs = [escape(p.get("excerpt", "")).replace("\n", "<br>")]
    paragraphs += [f"<b>{k}:</b> {escape(v)}" for k, v in facts]
    return Message(
        to=recipients,
        subject=f"New feedback on {_one_line(site.name)}",
        text=text.strip(),
        html=_html(paragraphs, link),
        reply_to=p.get("email"),
        tags=[row.event_type],
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
    paragraphs = [escape(head)]
    paragraphs.append("<br>".join(f"&bull; {escape(e)}" for e in excerpts) + (f"<br>...and {more} more" if more else ""))
    return Message(
        to=recipients,
        subject=f"{n} more feedback on {_one_line(site.name)}",
        text=text,
        html=_html(paragraphs, link),
        tags=["feedback.summary"],
    )
