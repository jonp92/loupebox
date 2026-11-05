import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import NotificationChannel, NotificationOutbox, OutboxStatus, Role
from app.models.user import utcnow
from app.notifications.base import SendResult
from tests.conftest import add_member, login, make_site, make_user
from tests.test_notifications import fake, make_channel  # noqa: F401  (fixtures)

BODY = {"provider": "fake", "name": "Ops", "extra_recipients": ["Ops@Example.com"]}


@pytest.fixture
def admin(client, db):
    site = make_site(db)
    user = make_user(db, "admin@example.com")
    add_member(db, user, site, Role.admin)
    return site, login(client, "admin@example.com")


def url(site, tail=""):
    return f"/sites/{site.id}/notifications{tail}"


# --- access -------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.viewer, Role.editor])
def test_only_admins_manage_notifications(client, db, fake, role):
    site = make_site(db)
    add_member(db, make_user(db, "u@example.com"), site, role)
    h = login(client, "u@example.com")
    channel = make_channel(db, site)
    cid = str(channel.id)

    calls = [
        client.get(url(site), headers=h),
        client.post(url(site), json=BODY, headers=h),
        client.patch(url(site, f"/{cid}"), json={"name": "x"}, headers=h),
        client.delete(url(site, f"/{cid}"), headers=h),
        client.post(url(site, f"/{cid}/test"), headers=h),
        client.get(url(site, "/deliveries"), headers=h),
        client.get("/notifications/providers", headers=h),
    ]
    assert [r.status_code for r in calls] == [403] * 7


def test_non_members_cannot_see_the_site_and_anonymous_is_rejected(client, db, fake):
    site = make_site(db)
    make_user(db, "out@example.com")
    h = login(client, "out@example.com")
    assert client.get(url(site), headers=h).status_code == 404
    assert client.get(url(site)).status_code == 401
    assert client.get("/notifications/providers").status_code == 401


def test_superadmin_acts_as_admin_everywhere(client, db, fake):
    site = make_site(db)
    make_user(db, "root@example.com", superadmin=True)
    h = login(client, "root@example.com")
    assert client.post(url(site), json=BODY, headers=h).status_code == 201
    assert client.get("/notifications/providers", headers=h).status_code == 200


def test_channels_are_scoped_to_their_site(client, db, admin, fake):
    site, h = admin
    other = make_site(db, "Other")
    foreign = make_channel(db, other)
    r = client.patch(url(site, f"/{foreign.id}"), json={"name": "x"}, headers=h)
    assert r.status_code == 404
    assert client.delete(url(site, f"/{foreign.id}"), headers=h).status_code == 404
    assert client.post(url(site, f"/{foreign.id}/test"), headers=h).status_code == 404
    assert client.get(url(site), headers=h).json() == []


# --- providers ----------------------------------------------------------------------------------


def test_provider_list_reports_configuration_and_schema(client, admin, fake, monkeypatch):
    _, h = admin
    monkeypatch.setattr(settings, "brevo_api_key", "")
    providers = {p["key"]: p for p in client.get("/notifications/providers", headers=h).json()}

    assert providers["brevo"]["configured"] is False
    assert providers["brevo"]["label"] == "Brevo (email)"
    assert providers["fake"]["configured"] is True
    assert providers["fake"]["config_schema"]["properties"]["prefix"]["type"] == "string"

    monkeypatch.setattr(settings, "brevo_api_key", "k")
    monkeypatch.setattr(settings, "notify_sender_email", "a@example.com")
    again = {p["key"]: p for p in client.get("/notifications/providers", headers=h).json()}
    assert again["brevo"]["configured"] is True


# --- create / update / delete -------------------------------------------------------------------


def test_create_applies_defaults_and_normalizes(client, admin, fake):
    site, h = admin
    r = client.post(
        url(site), json={**BODY, "extra_recipients": ["A@x.com", "a@X.com", "b@x.com"]}, headers=h
    )
    assert r.status_code == 201
    body = r.json()
    assert body["enabled"] is True and body["min_role"] == "admin"
    assert body["events"] == ["feedback.created"]
    assert body["extra_recipients"] == ["a@x.com", "b@x.com"]
    assert client.get(url(site), headers=h).json()[0]["id"] == body["id"]


def test_config_is_validated_and_stripped_to_declared_fields(client, admin, fake):
    site, h = admin
    assert client.post(url(site), json={**BODY, "config": {"prefix": 5}}, headers=h).status_code == 422
    r = client.post(url(site), json={**BODY, "config": {"prefix": "x", "api_key": "leak"}}, headers=h)
    assert r.status_code == 201
    assert r.json()["config"] == {"prefix": "x"}


@pytest.mark.parametrize(
    "patch",
    [
        {"provider": "nope"},
        {"events": ["feedback.deleted"]},
        {"extra_recipients": ["not-an-email"]},
        {"extra_recipients": [f"u{i}@x.com" for i in range(21)]},
        {"min_role": "owner"},
        {"name": ""},
    ],
)
def test_create_rejects_bad_input(client, admin, fake, patch):
    site, h = admin
    assert client.post(url(site), json={**BODY, **patch}, headers=h).status_code == 422


def test_cannot_enable_a_channel_whose_provider_is_unconfigured(client, admin, fake):
    site, h = admin
    fake_provider = fake
    fake_provider.configured = False

    assert client.post(url(site), json=BODY, headers=h).status_code == 409
    r = client.post(url(site), json={**BODY, "enabled": False}, headers=h)
    assert r.status_code == 201  # a disabled channel can be prepared ahead of the server setup

    cid = r.json()["id"]
    assert client.patch(url(site, f"/{cid}"), json={"enabled": True}, headers=h).status_code == 409
    assert client.patch(url(site, f"/{cid}"), json={"name": "renamed"}, headers=h).json()["name"] == "renamed"


def test_channel_limit_per_site(client, admin, fake):
    site, h = admin
    for _ in range(10):
        assert client.post(url(site), json=BODY, headers=h).status_code == 201
    assert client.post(url(site), json=BODY, headers=h).status_code == 409


def test_patch_updates_only_given_fields(client, admin, fake):
    site, h = admin
    cid = client.post(url(site), json=BODY, headers=h).json()["id"]

    r = client.patch(
        url(site, f"/{cid}"),
        json={"min_role": "editor", "events": [], "enabled": False, "name": None},
        headers=h,
    )

    body = r.json()
    assert (body["min_role"], body["events"], body["enabled"]) == ("editor", [], False)
    assert body["name"] == "Ops" and body["extra_recipients"] == ["ops@example.com"]
    assert body["provider"] == "fake"
    assert client.patch(url(site, f"/{cid}"), json={"config": {"prefix": 1}}, headers=h).status_code == 422


def test_delete_removes_the_channel_and_unknown_id_is_404(client, db, admin, fake):
    site, h = admin
    cid = client.post(url(site), json=BODY, headers=h).json()["id"]
    assert client.delete(url(site, f"/{cid}"), headers=h).status_code == 204
    assert db.scalar(select(NotificationChannel.id)) is None
    assert client.delete(url(site, f"/{cid}"), headers=h).status_code == 404


# --- test send ----------------------------------------------------------------------------------


def test_send_test_goes_only_to_the_caller(client, db, admin, fake):
    site, h = admin
    channel = make_channel(db, site, extra_recipients=["other@example.com"])

    r = client.post(url(site, f"/{channel.id}/test"), headers=h)

    assert r.json() == {"status": "sent", "error": None, "to": "admin@example.com"}
    assert [m.to for m in fake.sent] == [["admin@example.com"]]
    assert db.scalar(select(NotificationOutbox.id)) is None  # bypasses the queue and the cap


def test_send_test_reports_provider_failures(client, db, admin, fake):
    site, h = admin
    channel = make_channel(db, site)
    fake.results = [SendResult.failed("brevo 401: unauthorized")]
    r = client.post(url(site, f"/{channel.id}/test"), headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "failed" and "401" in r.json()["error"]


def test_send_test_works_on_a_disabled_channel_but_not_an_unconfigured_provider(client, db, admin, fake):
    site, h = admin
    channel = make_channel(db, site, enabled=False)
    assert client.post(url(site, f"/{channel.id}/test"), headers=h).json()["status"] == "sent"
    fake.configured = False
    assert client.post(url(site, f"/{channel.id}/test"), headers=h).status_code == 409


def test_send_test_is_rate_limited_per_admin(client, db, admin, fake):
    site, h = admin
    channel = make_channel(db, site)
    codes = [client.post(url(site, f"/{channel.id}/test"), headers=h).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
    assert len(fake.sent) == 5


# --- deliveries ---------------------------------------------------------------------------------


def test_deliveries_newest_first_capped_and_without_payload(client, db, admin, fake):
    site, h = admin
    channel = make_channel(db, site)
    other = make_site(db, "Other")
    now = utcnow()
    rows = [
        NotificationOutbox(
            channel_id=channel.id,
            site_id=site.id,
            event_type="feedback.created",
            payload={"excerpt": "private words", "email": "who@example.com"},
            created_at=now.replace(microsecond=i),
        )
        for i in range(60)
    ]
    rows[0].status, rows[0].last_error = OutboxStatus.failed, "brevo 400: bad"
    db.add_all(rows)
    db.add(NotificationOutbox(site_id=other.id, event_type="feedback.created", payload={}))
    db.commit()

    r = client.get(url(site, "/deliveries"), headers=h)

    data = r.json()
    assert len(data) == 50
    assert [d["created_at"] for d in data] == sorted((d["created_at"] for d in data), reverse=True)
    assert data[0]["channel_name"] == "ops" and data[0]["summary"] is False
    assert "private words" not in r.text and "who@example.com" not in r.text
    assert set(data[0]) == {
        "id",
        "channel_id",
        "channel_name",
        "event_type",
        "status",
        "attempts",
        "summary",
        "last_error",
        "created_at",
        "next_attempt_at",
        "sent_at",
    }


def test_deliveries_survive_channel_deletion(client, db, admin, fake):
    site, h = admin
    db.add(NotificationOutbox(site_id=site.id, event_type="feedback.created", payload={}, channel_id=None))
    db.commit()
    (d,) = client.get(url(site, "/deliveries"), headers=h).json()
    assert d["channel_id"] is None and d["channel_name"] is None


# --- secrets ------------------------------------------------------------------------------------


def test_server_secrets_never_appear_in_responses(client, db, admin, monkeypatch):
    site, h = admin
    monkeypatch.setattr(settings, "brevo_api_key", "xkeysib-TOP-SECRET")
    monkeypatch.setattr(settings, "notify_sender_email", "feedback@example.com")

    created = client.post(url(site), json={"provider": "brevo", "name": "Mail"}, headers=h)
    assert created.status_code == 201
    cid = created.json()["id"]
    responses = [
        created,
        client.get(url(site), headers=h),
        client.get("/notifications/providers", headers=h),
        client.get(url(site, "/deliveries"), headers=h),
        client.patch(url(site, f"/{cid}"), json={"name": "Mail2"}, headers=h),
    ]
    assert all("TOP-SECRET" not in r.text for r in responses)
    assert (
        client.post(
            url(site), json={"provider": "brevo", "name": "x", "config": {"api_key": "k"}}, headers=h
        ).status_code
        == 422
    )
