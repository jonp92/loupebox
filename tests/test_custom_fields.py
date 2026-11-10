import pytest
from sqlalchemy import select

from app.models import AuditEvent, Feedback, Role
from tests.conftest import SITE_ORIGIN, add_member, login, make_site, make_user

HEADERS = {"X-API-Key": "pk_test_Shop", "Origin": SITE_ORIGIN}

PLAN = {
    "id": "plan",
    "type": "select",
    "label": "Plan",
    "options": [{"value": "free", "label": "Free"}, {"value": "pro", "label": "Pro"}],
    "translations": {"de": {"label": "Tarif", "options": {"free": "Kostenlos"}}},
}
BETA = {"id": "beta", "type": "checkbox", "label": "Beta tester"}
COMPANY = {"id": "company", "type": "text", "label": "Company", "max_length": 10}


@pytest.fixture
def admin(client, db):
    site = make_site(db)
    add_member(db, make_user(db, "a@example.com"), site, Role.admin)
    return site, login(client, "a@example.com")


def save(client, site, h, fields):
    return client.patch(f"/sites/{site.id}", json={"custom_fields": fields}, headers=h)


def send(client, metadata):
    return client.post("/feedback", json={"message": "hello", "metadata": metadata}, headers=HEADERS)


def stored(db):
    return db.scalars(select(Feedback)).one().meta


# ---- defining fields


def test_an_admin_saves_fields_and_the_site_returns_them_with_defaults(client, admin):
    site, h = admin
    r = save(client, site, h, [PLAN, BETA])
    assert r.status_code == 200, r.text
    got = client.get(f"/sites/{site.id}", headers=h).json()["custom_fields"]
    assert [f["id"] for f in got] == ["plan", "beta"]
    assert got[1] == {
        **BETA,
        "required": False,
        "options": [],
        "max_length": None,
        "show_in_list": False,
        "translations": {},
    }


def test_only_an_admin_can_change_the_fields(client, db, admin):
    site, _ = admin
    add_member(db, make_user(db, "e@example.com"), site, Role.editor)
    editor = login(client, "e@example.com")
    assert save(client, site, editor, [BETA]).status_code in (403, 404)
    assert client.get(f"/sites/{site.id}", headers=editor).json()["custom_fields"] == []


@pytest.mark.parametrize(
    "bad",
    [
        [{**BETA, "id": "issue_type"}],  # reserved
        [{**BETA, "id": "Has Caps"}],
        [BETA, BETA],  # duplicate id
        [{"id": "p", "type": "select", "label": "P"}],  # select without options
        [{**BETA, "options": [{"value": "x", "label": "X"}]}],  # options on a checkbox
        [{**BETA, "max_length": 5}],  # max_length on a checkbox
        [{**PLAN, "options": [{"value": "a", "label": "A"}, {"value": "a", "label": "B"}]}],
        [{**PLAN, "translations": {"de": {"options": {"gold": "Gold"}}}}],  # translates a missing option
        [{**PLAN, "translations": {"not a locale": {"label": "x"}}}],
        [{**BETA, "label": "   "}],
        [{**BETA, "id": f"f{i}"} for i in range(11)],  # too many
        [{**BETA, "id": f"f{i}", "show_in_list": True} for i in range(3)],  # too many badges
        [{**BETA, "unknown": 1}],
    ],
)
def test_invalid_definitions_are_rejected_and_nothing_is_saved(client, admin, bad):
    site, h = admin
    assert save(client, site, h, bad).status_code == 422
    assert client.get(f"/sites/{site.id}", headers=h).json()["custom_fields"] == []


def test_at_most_eight_languages_per_site(client, admin):
    site, h = admin
    codes = ["de", "fr", "es", "it", "nl", "pt", "pl", "sv", "da"]
    fields = [{**BETA, "id": f"f{i}", "translations": {c: {"label": "x"}}} for i, c in enumerate(codes)]
    assert save(client, site, h, fields).status_code == 422
    assert save(client, site, h, fields[:8]).status_code == 200


def test_the_audit_log_records_that_fields_changed_but_not_their_labels(client, db, admin):
    site, h = admin
    save(client, site, h, [{**BETA, "label": "Secret label"}])
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "site.update")).one()
    assert event.details == {"custom_fields": "changed"}
    assert "Secret label" not in str(event.details) + event.summary


# ---- the form's config


def test_the_widget_config_lists_the_fields(client, admin):
    site, h = admin
    save(client, site, h, [PLAN])
    cfg = client.get("/feedback/config", headers=HEADERS).json()
    assert cfg["fields"][0]["translations"]["de"]["label"] == "Tarif"
    assert cfg["attachments"] == {"enabled": False}


# ---- submissions


def test_answers_are_stored_under_the_field_id(client, db, admin):
    site, h = admin
    save(client, site, h, [PLAN, BETA, COMPANY])
    assert (
        send(client, {"plan": "pro", "beta": True, "company": "  Acme  ", "extra": "kept"}).status_code == 201
    )
    assert stored(db) == {"plan": "pro", "beta": True, "company": "Acme", "extra": "kept"}


def test_an_answer_that_does_not_fit_is_dropped_but_the_feedback_is_kept(client, db, admin):
    site, h = admin
    save(client, site, h, [PLAN, BETA, COMPANY])
    r = send(client, {"plan": "gold", "beta": "yes", "company": 5})  # a removed option, a string, a number
    assert r.status_code == 201
    assert stored(db) == {}


def test_text_is_cut_to_the_fields_max_length(client, db, admin):
    site, h = admin
    save(client, site, h, [COMPANY])
    send(client, {"company": "x" * 50})
    assert stored(db) == {"company": "x" * 10}


def test_a_missing_required_field_is_a_422_naming_it(client, db, admin):
    site, h = admin
    save(client, site, h, [{**PLAN, "required": True}, {**BETA, "required": True}])
    r = send(client, {"beta": True})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "metadata", "plan"]
    assert (
        send(client, {"plan": "gold", "beta": True}).status_code == 422
    )  # a dropped answer counts as missing
    assert (
        send(client, {"plan": "free", "beta": False}).status_code == 422
    )  # a required checkbox must be ticked
    assert db.scalars(select(Feedback)).all() == []
    assert send(client, {"plan": "free", "beta": True}).status_code == 201


def test_a_site_without_fields_keeps_every_key(client, db, admin):
    send(client, {"anything": "goes", "n": 1})
    assert stored(db) == {"anything": "goes", "n": 1}
