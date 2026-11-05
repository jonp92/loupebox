from datetime import timedelta

import pytest

from app.core.config import settings
from app.models import NotificationOutbox, OutboxStatus, Role
from app.models.user import utcnow
from app.notifications.base import SendResult
from app.notifications.dispatcher import RETRY_DELAYS, process_due, purge_finished
from app.notifications.messages import build_message, build_summary
from app.notifications.recipients import resolve_recipients
from tests.conftest import add_member, make_site, make_user
from tests.test_notifications import fake, make_channel, outbox  # noqa: F401  (fixtures)


def queue(db, channel, n=1, excerpt="hello") -> list[NotificationOutbox]:
    rows = [
        NotificationOutbox(
            channel_id=channel.id,
            site_id=channel.site_id,
            event_type="feedback.created",
            payload={"type": "feedback.created", "feedback_id": "x", "excerpt": f"{excerpt} {i}"},
        )
        for i in range(n)
    ]
    db.add_all(rows)
    db.commit()
    return rows


def by_status(db) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in outbox(db):
        out[r.status.value] = out.get(r.status.value, 0) + 1
    return out


def make_held_due(db):
    for r in outbox(db):
        if r.status == OutboxStatus.held:
            r.next_attempt_at = utcnow() - timedelta(seconds=1)
    db.commit()


# --- recipients ---------------------------------------------------------------------------------


def test_recipients_by_minimum_role_plus_extras(db, fake):
    site = make_site(db)
    for email, role in [("v@x.com", Role.viewer), ("e@x.com", Role.editor), ("a@x.com", Role.admin)]:
        add_member(db, make_user(db, email), site, role)
    gone = make_user(db, "off@x.com")
    gone.is_active = False
    db.commit()
    add_member(db, gone, site, Role.admin)
    add_member(db, make_user(db, "other@x.com"), make_site(db, "Other"), Role.admin)  # other site

    editors = make_channel(db, site, extra_recipients=["Extra@x.com", "e@X.com"])
    editors.min_role = Role.editor
    db.commit()

    assert resolve_recipients(db, editors) == ["a@x.com", "e@x.com", "Extra@x.com"]
    editors.min_role = Role.viewer
    assert resolve_recipients(db, editors) == ["a@x.com", "e@x.com", "v@x.com", "Extra@x.com"]


def test_recipients_are_capped(db, fake, monkeypatch):
    monkeypatch.setattr(settings, "notify_max_recipients", 3)
    channel = make_channel(db, make_site(db), extra_recipients=[f"u{i}@x.com" for i in range(10)])
    assert len(resolve_recipients(db, channel)) == 3


def test_membership_changes_apply_to_queued_rows(db, fake):
    site = make_site(db)
    channel = make_channel(db, site, extra_recipients=[])
    channel.min_role = Role.viewer
    db.commit()
    queue(db, channel)
    add_member(db, make_user(db, "late@x.com"), site, Role.viewer)  # joins after the row was queued

    process_due(db)

    assert fake.sent[0].to == ["late@x.com"]


# --- templates ----------------------------------------------------------------------------------


def test_html_escapes_user_text(db, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "")
    site = make_site(db, "<b>Shop</b>\nInc")
    channel = make_channel(db, site)
    (row,) = queue(db, channel)
    row.payload = {
        "excerpt": "<script>alert(1)</script>\nline2",
        "name": "<img src=x>",
        "email": "a@x.com",
        "page_url": "https://x.com/?a=1&b=<2>",
        "rating": 4,
    }

    m = build_message(row, site, ["r@x.com"])

    assert "<script>" not in m.html and "<img" not in m.html and "<2>" not in m.html
    assert "&lt;script&gt;" in m.html and "line2" in m.html and "<br>" in m.html
    assert "<script>" in m.text  # plain text is not escaped
    assert m.subject == "New feedback on <b>Shop</b> Inc"  # one line, no header injection
    assert m.reply_to == "a@x.com" and m.to == ["r@x.com"]
    assert "Rating: 4" in m.text and "Open in Loupebox" not in m.html


def test_link_uses_public_url(db, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://admin.example.com/")
    site = make_site(db)
    (row,) = queue(db, make_channel(db, site))
    m = build_message(row, site, ["r@x.com"])
    deep = f"https://admin.example.com/sites/{site.id}/feedback/{row.payload['feedback_id']}"
    assert deep in m.text
    assert f'href="{deep}"' in m.html


def test_summary_lists_first_excerpts_and_the_remainder(db):
    site = make_site(db)
    rows = queue(db, make_channel(db, site), n=8, excerpt="x" * 300)

    m = build_summary(rows, site, ["r@x.com"])

    assert m.subject == "8 more feedback on Shop"
    assert m.text.count("\n- ") == 5 and "...and 3 more" in m.text
    assert all(len(line) <= 142 for line in m.text.splitlines() if line.startswith("- "))
    assert m.reply_to is None


# --- hourly cap and summary ---------------------------------------------------------------------


def test_cap_holds_overflow_without_sending(db, fake):
    channel = make_channel(db, make_site(db))
    queue(db, channel, n=7)

    process_due(db)

    assert by_status(db) == {"sent": 5, "held": 2}
    assert len(fake.sent) == 5
    held = [r for r in outbox(db) if r.status == OutboxStatus.held]
    assert {r.attempts for r in held} == {0}
    assert len({r.next_attempt_at for r in held}) == 1  # both wait for the same summary
    wait = held[0].next_attempt_at.replace(tzinfo=utcnow().tzinfo) - utcnow()
    assert timedelta(minutes=14) < wait <= timedelta(minutes=15)
    assert process_due(db) == 0  # summary not due yet


def test_summary_goes_out_once_after_the_delay(db, fake):
    channel = make_channel(db, make_site(db))
    queue(db, channel, n=8)
    process_due(db)
    make_held_due(db)

    assert process_due(db) == 3

    assert len(fake.sent) == 6
    assert fake.sent[-1].subject == "3 more feedback on Shop"
    assert by_status(db) == {"sent": 8}
    summarized = [r for r in outbox(db) if r.summary_id]
    assert len(summarized) == 3 and len({r.summary_id for r in summarized}) == 1
    assert process_due(db) == 0


def test_late_arrivals_join_the_pending_summary(db, fake):
    channel = make_channel(db, make_site(db))
    queue(db, channel, n=6)
    process_due(db)
    first_due = next(r for r in outbox(db) if r.status == OutboxStatus.held).next_attempt_at

    queue(db, channel, n=1)
    process_due(db)

    held = [r for r in outbox(db) if r.status == OutboxStatus.held]
    assert len(held) == 2 and {r.next_attempt_at for r in held} == {first_due}


def test_cap_is_per_channel(db, fake):
    site = make_site(db)
    a, b = make_channel(db, site), make_channel(db, site)
    queue(db, a, n=6)
    queue(db, b, n=2)
    process_due(db)
    assert sorted(by_status(db).items()) == [("held", 1), ("sent", 7)]


def test_summary_counts_as_one_send_not_one_per_row(db, fake, monkeypatch):
    monkeypatch.setattr(settings, "notify_hourly_cap", 3)
    channel = make_channel(db, make_site(db))
    queue(db, channel, n=7)  # 3 sent, 4 held
    process_due(db)
    make_held_due(db)
    process_due(db)  # summary of 4
    for r in outbox(db):
        if not r.summary_id:
            r.sent_at = utcnow() - timedelta(hours=2)  # the 3 individual sends age out of the window
    db.commit()

    queue(db, channel)
    process_due(db)

    # Window now holds one summary email. Counted per covered row it would read 4 and hold this one.
    assert by_status(db) == {"sent": 8}


def test_old_sends_age_out_of_the_window(db, fake):
    channel = make_channel(db, make_site(db))
    queue(db, channel, n=5)
    process_due(db)
    for r in outbox(db):
        r.sent_at = utcnow() - timedelta(hours=1, minutes=1)
    db.commit()
    queue(db, channel)
    process_due(db)
    assert by_status(db) == {"sent": 6}


def test_summary_retry_then_final_failure(db, fake):
    channel = make_channel(db, make_site(db))
    queue(db, channel, n=7)
    process_due(db)
    fake.results = [SendResult.retry("503")] * (len(RETRY_DELAYS) + 1)

    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        make_held_due(db)
        before = utcnow()
        assert process_due(db) == 2
        rows = [r for r in outbox(db) if r.status == OutboxStatus.held]
        assert len(rows) == 2 and {r.attempts for r in rows} == {attempt}
        due = rows[0].next_attempt_at.replace(tzinfo=before.tzinfo)
        assert before + delay <= due <= utcnow() + delay
        assert process_due(db) == 0

    make_held_due(db)
    process_due(db)
    assert by_status(db) == {"sent": 5, "failed": 2}


def test_summary_permanent_failure_fails_all_covered_rows(db, fake):
    channel = make_channel(db, make_site(db))
    queue(db, channel, n=7)
    process_due(db)
    fake.results = [SendResult.failed("bad key")]
    make_held_due(db)
    process_due(db)
    assert by_status(db) == {"sent": 5, "failed": 2}
    assert {r.last_error for r in outbox(db) if r.status == OutboxStatus.failed} == {"bad key"}


@pytest.mark.parametrize("how", ["disabled", "deleted"])
def test_held_rows_of_a_removed_channel_fail_instead_of_lingering(db, fake, how):
    channel = make_channel(db, make_site(db))
    queue(db, channel, n=6)
    process_due(db)
    if how == "disabled":
        channel.enabled = False
    else:
        db.delete(channel)
        for r in outbox(db):
            r.channel_id = None  # what ON DELETE SET NULL does (SQLite does not enforce it)
    db.commit()
    make_held_due(db)

    process_due(db)

    assert by_status(db) == {"sent": 5, "failed": 1}
    assert len(fake.sent) == 5


def test_purge_removes_only_old_finished_rows(db, fake):
    site = make_site(db)
    channel = make_channel(db, site)
    old = utcnow() - timedelta(days=settings.notify_retention_days + 1)
    rows = queue(db, channel, n=5)
    for row, status in zip(
        rows,
        [OutboxStatus.sent, OutboxStatus.failed, OutboxStatus.pending, OutboxStatus.held, OutboxStatus.sent],
        strict=True,
    ):
        row.status = status
        row.created_at = old
    rows[4].created_at = utcnow()  # recent sent row stays
    db.commit()
    assert purge_finished(db, utcnow()) == 2
    assert {r.status for r in outbox(db)} == {OutboxStatus.pending, OutboxStatus.held, OutboxStatus.sent}
    assert len(outbox(db)) == 3


def test_html_escapes_site_name_and_only_links_http_pages(db, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "")
    site = make_site(db, "<b>Shop</b>")
    (row,) = queue(db, make_channel(db, site))
    row.payload = {"excerpt": "hi", "page_url": "javascript:alert(1)"}

    m = build_message(row, site, ["r@x.com"])

    assert "<b>Shop</b>" not in m.html and "&lt;b&gt;Shop&lt;/b&gt;" in m.html
    assert "javascript:alert(1)" in m.html and 'href="javascript' not in m.html

    row.payload = {"excerpt": "hi", "page_url": "https://x.com/a?b=1&c=2"}
    assert 'href="https://x.com/a?b=1&amp;c=2"' in build_message(row, site, ["r@x.com"]).html


def test_email_shows_logo_only_when_public_url_is_set(db, monkeypatch):
    site = make_site(db)
    (row,) = queue(db, make_channel(db, site))
    monkeypatch.setattr(settings, "public_url", "")
    assert "email-logo.png" not in build_message(row, site, ["r@x.com"]).html
    monkeypatch.setattr(settings, "public_url", "https://admin.example.com/")
    assert 'src="https://admin.example.com/email-logo.png"' in build_message(row, site, ["r@x.com"]).html
