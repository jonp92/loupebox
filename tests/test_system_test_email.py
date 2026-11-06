import pytest

from app.models import Role
from app.notifications.base import SendResult
from tests.conftest import add_member, login, make_site, make_user
from tests.test_notifications import fake  # noqa: F401  (fixture)


@pytest.fixture
def h(client, db):
    make_user(db, "root@example.com", superadmin=True)
    return login(client, "root@example.com")


def send(client, h, provider="fake"):
    return client.post("/system/test-email", json={"provider": provider}, headers=h)


def test_goes_only_to_the_caller_through_the_chosen_provider(client, h, fake):
    r = send(client, h)
    assert r.json() == {"status": "sent", "error": None, "to": "root@example.com"}
    assert [m.to for m in fake.sent] == [["root@example.com"]]
    assert fake.sent[0].tags == ["test"] and "Fake" in fake.sent[0].text


def test_reports_provider_failures(client, h, fake):
    fake.results = [SendResult.failed("smtp 535: bad credentials")]
    r = send(client, h)
    assert r.status_code == 200
    assert r.json()["status"] == "failed" and "535" in r.json()["error"]


def test_provider_exceptions_do_not_become_a_500(client, h, fake, monkeypatch):
    def boom(message, config):
        raise RuntimeError("boom")

    monkeypatch.setattr(fake, "send", boom)
    assert send(client, h).json()["status"] == "retry"


def test_rejects_unknown_unconfigured_and_non_email_providers(client, h, fake):
    assert send(client, h, "nope").status_code == 422
    assert send(client, h, "webhook").status_code == 422  # posts to an endpoint, not to people
    fake.configured = False
    assert send(client, h).status_code == 409
    assert fake.sent == []


def test_superadmin_only(client, db, fake):
    owner = make_user(db, "own@example.com")
    add_member(db, owner, make_site(db), Role.admin)
    assert send(client, login(client, "own@example.com")).status_code == 403
    assert fake.sent == []


def test_rate_limited(client, h, fake):
    codes = [send(client, h).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
