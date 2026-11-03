import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import AuditEvent, Feedback, FeedbackReply, FeedbackStatus, NotificationOutbox, Role
from app.notifications import registry
from app.notifications.base import SendResult
from tests.conftest import make_site
from tests.test_bulk_filters import as_role, seed
from tests.test_notifications import FakeProvider, make_channel

PERSON = "visitor@example.org"


@pytest.fixture
def mail(monkeypatch):
    """A configured mail provider that records what it is asked to send."""
    provider = FakeProvider()
    monkeypatch.setitem(registry._providers, "fake", provider)
    monkeypatch.setattr(settings, "mail_provider", "fake")
    return provider


@pytest.fixture
def setup(client, db, mail):
    site = make_site(db, "Shop")
    h = as_role(client, db, site, Role.editor, "ed@example.com")
    return site, h, seed(db, site, message="The cart is broken", email=PERSON)


def url(site, item, tail=""):
    return f"/sites/{site.id}/feedback/{item.id}/replies{tail}"


def reply(client, site, item, h, body="Thanks, fixing it now."):
    return client.post(url(site, item), headers=h, json={"body": body})


def test_reply_is_emailed_to_the_submitter_and_recorded(client, db, setup, mail):
    site, h, item = setup
    r = reply(client, site, item, h)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "sent" and r.json()["direction"] == "outbound" and r.json()["source"] == "ui"
    (sent,) = mail.sent
    assert sent.to == [PERSON] and sent.reply_to == "ed@example.com"
    assert sent.subject == "Re: your feedback on Shop"
    assert "Thanks, fixing it now." in sent.text and "The cart is broken" in sent.text
    assert db.scalar(select(FeedbackReply.message_id)) == "m-1"
    thread = client.get(url(site, item), headers=h).json()
    assert thread["available"] is True
    assert [(i["body"], i["author_name"]) for i in thread["items"]] == [("Thanks, fixing it now.", "ed@example.com")]


def test_reply_text_is_escaped_in_html(client, setup, mail):
    site, h, item = setup
    reply(client, site, item, h, body="<script>alert(1)</script>\nline two")
    html = mail.sent[0].html
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html and "line two" in html


def test_reply_count_shows_in_list_and_detail(client, db, setup, mail):
    site, h, item = setup
    mail.results = [SendResult.failed("smtp 550: recipient refused")]
    reply(client, site, item, h)  # a failed send is not a reply the person got
    assert client.get(f"/sites/{site.id}/feedback/{item.id}", headers=h).json()["reply_count"] == 0
    reply(client, site, item, h)
    assert client.get(f"/sites/{site.id}/feedback/{item.id}", headers=h).json()["reply_count"] == 1
    assert client.get(f"/sites/{site.id}/feedback", headers=h).json()["items"][0]["reply_count"] == 1


def test_viewer_reads_but_cannot_send(client, db, setup):
    site, _, item = setup
    v = as_role(client, db, site, Role.viewer, "v@example.com")
    assert client.get(url(site, item), headers=v).status_code == 200
    assert reply(client, site, item, v).status_code == 403


def test_other_sites_item_is_not_found(client, db, setup):
    site, _, item = setup
    other = make_site(db, "Other")
    h2 = as_role(client, db, other, Role.admin, "adm@example.com")
    assert client.get(url(other, item), headers=h2).status_code == 404
    assert reply(client, other, item, h2).status_code == 404
    assert client.get(url(site, item), headers=h2).status_code == 404  # not a member


@pytest.mark.parametrize("body", ["", "   ", "x" * 5001])
def test_bad_body_rejected(client, setup, body):
    site, h, item = setup
    assert reply(client, site, item, h, body=body).status_code == 422


def test_cannot_reply_without_email_or_to_spam_or_without_provider(client, db, setup, mail, monkeypatch):
    site, h, item = setup
    no_email = seed(db, site, message="anon")
    spam = seed(db, site, message="buy", email=PERSON, status=FeedbackStatus.spam)
    assert reply(client, site, no_email, h).status_code == 409
    assert reply(client, site, spam, h).status_code == 409
    mail.configured = False
    assert reply(client, site, item, h).status_code == 409
    assert client.get(url(site, item), headers=h).json()["available"] is False
    assert mail.sent == [] and db.scalar(select(FeedbackReply)) is None


def test_failed_send_is_recorded_with_the_reason(client, setup, mail):
    site, h, item = setup
    mail.results = [SendResult.failed("smtp 550: recipient refused")]
    r = reply(client, site, item, h)
    assert r.status_code == 201
    assert (r.json()["status"], r.json()["retryable"], r.json()["error"]) == ("failed", False, "smtp 550: recipient refused")
    assert client.post(url(site, item, f"/{r.json()['id']}/retry"), headers=h).status_code == 409  # rejected for good


def test_temporary_failure_can_be_retried_by_another_editor(client, db, setup, mail):
    site, h, item = setup
    mail.results = [SendResult.retry("smtp 451: try later")]
    first = reply(client, site, item, h).json()
    assert (first["status"], first["retryable"]) == ("failed", True)
    h2 = as_role(client, db, site, Role.editor, "ed2@example.com")
    r = client.post(url(site, item, f"/{first['id']}/retry"), headers=h2)
    assert r.status_code == 200 and r.json()["status"] == "sent" and r.json()["error"] is None
    assert r.json()["id"] == first["id"] and r.json()["author_name"] == "ed2@example.com"
    assert mail.sent[-1].reply_to == "ed2@example.com" and len(mail.sent) == 2
    assert client.post(url(site, item, f"/{first['id']}/retry"), headers=h2).status_code == 409  # already sent


def test_retry_of_unknown_reply_is_404(client, setup):
    import uuid

    site, h, item = setup
    assert client.post(url(site, item, f"/{uuid.uuid4()}/retry"), headers=h).status_code == 404


def test_per_item_limit_counts_sent_replies_only(client, setup, mail, monkeypatch):
    site, h, item = setup
    monkeypatch.setattr(settings, "reply_max_per_item", 2)
    mail.results = [SendResult.failed("nope")]
    reply(client, site, item, h)  # failed: does not use up the allowance
    assert reply(client, site, item, h).status_code == 201
    assert reply(client, site, item, h).status_code == 201
    assert reply(client, site, item, h).status_code == 409


def test_site_hourly_limit(client, db, setup, monkeypatch):
    site, h, item = setup
    monkeypatch.setattr(settings, "reply_site_hourly_limit", 2)
    monkeypatch.setattr(settings, "reply_max_per_item", 10)
    other = seed(db, site, message="two", email="b@example.org")
    assert reply(client, site, item, h).status_code == 201
    assert reply(client, site, other, h).status_code == 201
    r = reply(client, site, item, h)
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_audit_records_ids_and_length_never_text_or_address(client, db, setup):
    site, h, item = setup
    reply_id = reply(client, site, item, h, body="secret plan").json()["id"]
    (event,) = db.scalars(select(AuditEvent).where(AuditEvent.action == "feedback.reply"))
    assert event.details == {"reply_id": reply_id, "status": "sent", "length": 11}
    assert "secret plan" not in str(event.__dict__) and PERSON not in str(event.__dict__)


def test_replies_go_when_the_feedback_is_deleted(client, db, setup):
    site, h, item = setup
    item_id = item.id
    reply(client, site, item, h)
    admin = as_role(client, db, site, Role.admin, "adm@example.com")
    assert client.delete(f"/sites/{site.id}/feedback/{item.id}", headers=admin).status_code == 204
    db.expire_all()
    assert db.scalar(select(Feedback.id).where(Feedback.id == item_id)) is None
    if db.bind.dialect.name == "postgresql":  # the cascade is the database's; SQLite does not enforce it
        assert db.scalar(select(FeedbackReply)) is None


def test_replied_event_goes_to_webhook_channels_only_and_carries_no_text(client, db, setup, mail):
    site, h, item = setup
    hook = make_channel(db, site, provider="webhook", extra_recipients=[], events=["feedback.created", "feedback.replied"])
    make_channel(db, site, events=["feedback.replied"])  # an email channel: the team is not mailed about its own replies
    make_channel(db, site, provider="webhook", extra_recipients=[], events=["feedback.created"])  # not subscribed
    mail.results = [SendResult.failed("nope")]
    reply(client, site, item, h)  # a failed send is not an event
    assert db.scalar(select(NotificationOutbox)) is None
    body = "private words"
    reply_id = reply(client, site, item, h, body=body).json()["id"]
    (row,) = db.scalars(select(NotificationOutbox))
    assert row.channel_id == hook.id and row.event_type == "feedback.replied"
    assert row.payload == {"type": "feedback.replied", "feedback_id": str(item.id), "reply_id": reply_id, "length": len(body)}
