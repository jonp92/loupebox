"""Per-channel filters: which items a channel hears about."""

import pytest
from sqlalchemy import select

from app.models import AuditEvent, Feedback, FeedbackReply, NotificationOutbox
from app.notifications.filters import NO_TYPE, matches
from app.notifications.outbox import enqueue_reply_sent
from tests.conftest import SITE_ORIGIN, make_site
from tests.test_notification_api import BODY, admin, url  # noqa: F401  (fixtures)
from tests.test_notifications import fake, make_channel  # noqa: F401  (fixtures)

HEADERS = {"X-API-Key": "pk_test_Shop", "Origin": SITE_ORIGIN}


def item(**kw) -> Feedback:
    meta = {"issue_type": kw.pop("issue_type")} if "issue_type" in kw else {}
    return Feedback(message="m", meta=meta, **kw)


@pytest.mark.parametrize(
    ("filters", "feedback", "expected"),
    [
        ({}, item(), True),
        (None, item(), True),
        ({"issue_types": ["bug", "idea"]}, item(issue_type="idea"), True),
        ({"issue_types": ["bug"]}, item(issue_type="idea"), False),
        ({"issue_types": ["bug"]}, item(), False),
        ({"issue_types": [NO_TYPE]}, item(), True),
        ({"issue_types": [NO_TYPE, "bug"]}, item(issue_type="bug"), True),
        ({"issue_types": [NO_TYPE]}, item(issue_type="bug"), False),
        ({"rating_max": 2}, item(rating=2), True),
        ({"rating_max": 2}, item(rating=3), False),
        ({"rating_min": 4}, item(rating=4), True),
        ({"rating_min": 4}, item(rating=3), False),
        ({"rating_min": 2, "rating_max": 4}, item(rating=5), False),
        ({"rating_min": 1}, item(), False),  # unrated never matches a rating filter
        ({"has_email": True}, item(email="a@example.com"), True),
        ({"has_email": True}, item(), False),
        ({"has_email": False}, item(), True),
        ({"has_email": False}, item(email="a@example.com"), False),
        ({"page_contains": "/PRICING"}, item(page_url="https://x.example/pricing?a=1"), True),
        ({"page_contains": "/pricing"}, item(page_url="https://x.example/docs"), False),
        ({"page_contains": "/pricing"}, item(), False),
        # All set fields must match.
        ({"issue_types": ["bug"], "rating_max": 2}, item(issue_type="bug", rating=5), False),
        ({"issue_types": ["bug"], "rating_max": 2}, item(issue_type="bug", rating=1), True),
        # Unreadable stored filters fail open rather than drop notifications.
        ({"rating_max": 99}, item(rating=5), True),
        ({"nonsense": 1}, item(), True),
    ],
)
def test_matches(filters, feedback, expected):
    assert matches(filters, feedback) is expected


def submit(client, **kw):
    r = client.post("/feedback", json={"message": "hello", **kw}, headers=HEADERS)
    assert r.status_code == 201, r.text


def queued(db) -> set:
    return {r.channel_id for r in db.scalars(select(NotificationOutbox))}


def test_only_matching_channels_get_the_item(client, db, fake):
    site = make_site(db)
    everything = make_channel(db, site)
    bugs = make_channel(db, site, filters={"issue_types": ["bug"]})
    low = make_channel(db, site, filters={"rating_max": 2})

    submit(client, metadata={"issue_type": "idea"}, rating=5)
    assert queued(db) == {everything.id}
    submit(client, metadata={"issue_type": "bug"}, rating=1, email="a@example.com")
    assert queued(db) == {everything.id, bugs.id, low.id}


def test_replies_follow_the_filters_of_the_item(client, db, fake):
    site = make_site(db)
    fake.uses_recipients = False  # replies only go to channels that feed other systems, like webhooks
    bugs = make_channel(db, site, events=["feedback.replied"], filters={"issue_types": ["bug"]})
    for kind, expected in (("idea", set()), ("bug", {bugs.id})):
        fb = Feedback(site_id=site.id, message="m", meta={"issue_type": kind}, content_hash="h", ip_hash="i")
        db.add(fb)
        db.flush()
        enqueue_reply_sent(db, fb, FeedbackReply(feedback_id=fb.id, body="thanks"))
        db.commit()
        assert queued(db) == expected


def test_filters_are_saved_returned_and_audited(client, db, admin, fake):
    site, h = admin
    wanted = {
        "issue_types": ["bug", "bug"],
        "rating_max": 2,
        "has_email": True,
        "page_contains": " /pricing ",
    }
    created = client.post(url(site), json={**BODY, "filters": wanted}, headers=h)
    assert created.status_code == 201, created.text
    assert created.json()["filters"] == {
        "issue_types": ["bug"],
        "rating_min": None,
        "rating_max": 2,
        "has_email": True,
        "page_contains": "/pricing",
    }
    path = url(site, f"/{created.json()['id']}")

    def patch(**body):
        r = client.patch(path, json=body, headers=h)
        assert r.status_code == 200, r.text
        return r.json()["filters"]

    assert patch(filters={"rating_max": 1}) == {
        **created.json()["filters"],
        "issue_types": [],
        "rating_max": 1,
        "has_email": None,
        "page_contains": "",
    }
    assert patch(name="renamed")["rating_max"] == 1  # untouched
    assert patch(filters=None)["rating_max"] == 1  # null means leave as is

    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "channel.update")).first()
    assert "filters" in event.details and "filters" in event.summary


@pytest.mark.parametrize(
    "bad",
    [
        {"rating_min": 4, "rating_max": 2},
        {"rating_max": 6},
        {"issue_types": ["Not Valid!"]},
        {"issue_types": [f"t{i}" for i in range(21)]},
        {"page_contains": "x" * 201},
        {"surprise": True},
    ],
)
def test_bad_filters_are_refused(client, admin, fake, bad):
    site, h = admin
    assert client.post(url(site), json={**BODY, "filters": bad}, headers=h).status_code == 422


def test_send_test_ignores_the_filters(client, db, admin, fake):
    site, h = admin
    channel = make_channel(db, site, filters={"rating_max": 1})
    assert client.post(url(site, f"/{channel.id}/test"), headers=h).status_code == 200
    assert len(fake.sent) == 1
