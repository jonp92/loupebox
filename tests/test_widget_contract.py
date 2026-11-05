"""What the embeddable widget (web/widget) sends and how the server treats it.

The widget's own tests pin the exact payload it builds; these pin that the API accepts that shape and
that issue-type badges, which travel as `metadata.issue_type`, are usable: filterable, exportable, and
safe to put in emails and webhooks.
"""

import csv
import io

import pytest
from sqlalchemy import select

from app.api.feedback_routes import CSV_COLUMNS
from app.models import Feedback, FeedbackStatus, Role
from app.notifications.events import FeedbackCreated
from app.notifications.messages import build_message
from tests.conftest import SITE_ORIGIN, add_member, login, make_site, make_user
from tests.test_notifications import fake, make_channel  # noqa: F401

HEADERS = {"X-API-Key": "pk_test_Shop", "Origin": SITE_ORIGIN}
# Exactly the keys the widget sends (see widget/test/core.test.mjs "sends the contract").
WIDGET_BODY = {
    "message": "The export button does nothing",
    "rating": 4,
    "name": "Ada",
    "email": "ada@example.com",
    "page_url": "https://shop.example.com/pricing?x=1",
    "metadata": {"widget_version": "1.0.0", "issue_type": "bug", "route": "/pricing", "plan": "pro"},
    "website": "",
}


def submit(client, **override):
    return client.post("/feedback", json={**WIDGET_BODY, **override}, headers=HEADERS)


@pytest.fixture
def shop(client, db):
    site = make_site(db)
    add_member(db, make_user(db, "v@example.com"), site, Role.viewer)
    return site, login(client, "v@example.com")


def test_the_widgets_payload_is_accepted_and_stored(client, db, shop):
    r = submit(client)
    assert r.status_code == 201
    item = db.scalars(select(Feedback)).one()
    assert item.meta == WIDGET_BODY["metadata"] and item.status == FeedbackStatus.new
    assert item.page_url == WIDGET_BODY["page_url"] and item.rating == 4


def test_minimal_widget_payload(client, db, shop):
    r = client.post(
        "/feedback",
        json={"message": "hi", "metadata": {"widget_version": "1.0.0"}, "website": ""},
        headers=HEADERS,
    )
    assert r.status_code == 201


def test_the_admin_api_returns_the_metadata_the_ui_shows_as_a_badge(client, db, shop):
    site, h = shop
    submit(client)
    [item] = client.get(f"/sites/{site.id}/feedback", headers=h).json()["items"]
    assert item["metadata"]["issue_type"] == "bug"


def test_filter_by_issue_type(client, db, shop):
    site, h = shop
    for kind, text in [("bug", "crash one"), ("bug", "crash two"), ("idea", "dark mode"), (None, "no badge")]:
        meta = {"issue_type": kind} if kind else {}
        submit(client, message=text, metadata=meta, email=None)
    url = f"/sites/{site.id}/feedback"
    messages = lambda qs: sorted(i["message"] for i in client.get(url + qs, headers=h).json()["items"])
    assert messages("?issue_type=bug") == ["crash one", "crash two"]
    assert messages("?issue_type=idea") == ["dark mode"]
    assert messages("?issue_type=praise") == []
    assert len(messages("")) == 4
    assert messages("?issue_type=bug&q=two") == ["crash two"]
    assert client.get(url + "?issue_type=Bad Value", headers=h).status_code == 422


def test_issue_type_counts_for_the_filter_dropdown(client, db, shop):
    site, h = shop
    for kind in ["bug", "bug", "idea"]:
        submit(
            client,
            message=f"{kind} {len(db.scalars(select(Feedback)).all())}",
            metadata={"issue_type": kind},
            email=None,
        )
    submit(client, message="spammy", metadata={"issue_type": "praise"}, email=None)
    spam = db.scalars(select(Feedback).where(Feedback.message == "spammy")).one()
    spam.status = FeedbackStatus.spam
    db.commit()
    submit(client, message="weird", metadata={"issue_type": "<script>alert(1)</script>"}, email=None)
    r = client.get(f"/sites/{site.id}/feedback/issue-types", headers=h)
    assert r.json() == [{"id": "bug", "count": 2}, {"id": "idea", "count": 1}]  # no spam, nothing unsafe


def test_issue_type_is_scoped_to_the_site_and_role(client, db, shop):
    site, h = shop
    other = make_site(db, "Other")
    db.add(
        Feedback(
            site_id=other.id, message="theirs", content_hash="h", ip_hash="i", meta={"issue_type": "bug"}
        )
    )
    db.commit()
    assert client.get(f"/sites/{site.id}/feedback/issue-types", headers=h).json() == []
    assert client.get(f"/sites/{other.id}/feedback/issue-types", headers=h).status_code == 404
    assert client.get(f"/sites/{site.id}/feedback/issue-types").status_code == 401


def test_csv_has_an_issue_type_column_and_filters(client, db, shop):
    site, h = shop
    submit(client, message="a bug", metadata={"issue_type": "bug"}, email=None)
    submit(client, message="an idea", metadata={"issue_type": "idea"}, email=None)
    submit(client, message="forged", metadata={"issue_type": "=HYPERLINK(1)"}, email=None)
    r = client.get(f"/sites/{site.id}/feedback/export.csv", headers=h)
    rows = {row["message"]: row for row in csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")))}
    assert "issue_type" in CSV_COLUMNS
    assert rows["a bug"]["issue_type"] == "bug" and rows["an idea"]["issue_type"] == "idea"
    assert rows["forged"]["issue_type"] == ""  # not a plain id, so not exported as one
    only = client.get(f"/sites/{site.id}/feedback/export.csv?issue_type=bug", headers=h)
    assert [r["message"] for r in csv.DictReader(io.StringIO(only.content.decode("utf-8-sig")))] == ["a bug"]


def test_notification_events_carry_a_safe_issue_type(client, db, shop):
    submit(client)
    item = db.scalars(select(Feedback)).one()
    assert FeedbackCreated.from_feedback(item).issue_type == "bug"
    item.meta = {"issue_type": "<b>x</b>"}
    assert FeedbackCreated.from_feedback(item).issue_type is None
    item.meta = {"issue_type": 5}
    assert FeedbackCreated.from_feedback(item).issue_type is None
    item.meta = {}
    assert FeedbackCreated.from_feedback(item).issue_type is None


def test_the_email_says_what_kind_of_feedback_it_is(client, db, shop, fake):
    site = shop[0]
    make_channel(db, site)
    submit(client, metadata={"issue_type": "feature-request"})
    from app.models import NotificationOutbox

    row = db.scalars(select(NotificationOutbox)).one()
    assert row.payload["issue_type"] == "feature-request"
    message = build_message(row, site, ["ops@example.com"])
    assert "Type: Feature request" in message.text and "Feature request" in message.html
    assert message.event["data"]["issue_type"] == "feature-request"  # webhooks get it too


def test_old_outbox_rows_without_the_field_still_render(db, shop):
    from app.models import NotificationOutbox

    site = shop[0]
    row = NotificationOutbox(
        site_id=site.id,
        event_type="feedback.created",
        payload={"type": "feedback.created", "feedback_id": "x", "excerpt": "old"},
    )
    message = build_message(row, site, ["a@example.com"])
    assert "Type:" not in message.text
