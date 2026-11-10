import csv
import io

import pytest

from app.models import AuditEvent, Feedback, FeedbackStatus, Role
from tests.conftest import add_member, login, make_site, make_user

FIELDS = [
    {
        "id": "plan",
        "type": "select",
        "label": "Plan",
        "required": False,
        "max_length": None,
        "show_in_list": False,
        "translations": {},
        "options": [{"value": "free", "label": "Free"}, {"value": "pro", "label": "Pro"}],
    },
    {
        "id": "beta",
        "type": "checkbox",
        "label": "Beta tester",
        "required": False,
        "options": [],
        "max_length": None,
        "show_in_list": False,
        "translations": {},
    },
    {
        "id": "company",
        "type": "text",
        "label": "Company",
        "required": False,
        "options": [],
        "max_length": None,
        "show_in_list": False,
        "translations": {},
    },
]


@pytest.fixture
def site(db):
    return make_site(db, "Shop", custom_fields=FIELDS)


@pytest.fixture
def h(client, db, site):
    add_member(db, make_user(db, "v@example.com"), site, Role.viewer)  # filtering is a viewer's right
    return login(client, "v@example.com")


def seed(db, site, message, meta, **kw):
    db.add(Feedback(site_id=site.id, message=message, meta=meta, content_hash=message, ip_hash="i", **kw))
    db.commit()


@pytest.fixture
def rows(db, site):
    seed(db, site, "a", {"plan": "pro", "beta": True, "company": "Acme Corp"})
    seed(db, site, "b", {"plan": "free", "beta": False, "company": "100% Legit"})
    seed(db, site, "c", {"plan": "pro", "beta": False})
    seed(db, site, "d", {"plan": "gone", "extra": "x"})  # an option the site has since removed
    seed(db, site, "e", {})


def listed(client, site, h, *cf, **params):
    r = client.get(f"/sites/{site.id}/feedback", params={"cf": list(cf), **params}, headers=h)
    assert r.status_code == 200, r.text
    return sorted(i["message"] for i in r.json()["items"])


def test_a_choice_matches_its_stored_value(client, site, h, rows):
    assert listed(client, site, h, "plan:pro") == ["a", "c"]
    assert listed(client, site, h, "plan:gone") == ["d"]  # a removed option can still be found


def test_a_checkbox_is_yes_or_no_as_stored(client, site, h, rows):
    assert listed(client, site, h, "beta:true") == ["a"]
    assert listed(client, site, h, "beta:false") == ["b", "c"]  # items that never answered are in neither


def test_text_is_a_case_insensitive_contains_that_takes_wildcards_literally(client, site, h, rows):
    assert listed(client, site, h, "company:acme") == ["a"]
    assert listed(client, site, h, "company:100%") == ["b"]
    assert listed(client, site, h, "company:%") == ["b"]  # a percent sign is not "anything"
    assert listed(client, site, h, "company:_") == []


def test_filters_combine_with_each_other_and_with_the_rest(client, db, site, h, rows):
    assert listed(client, site, h, "plan:pro", "beta:false") == ["c"]
    seed(db, site, "f", {"plan": "pro"}, status=FeedbackStatus.read)
    assert listed(client, site, h, "plan:pro", status="read") == ["f"]
    assert listed(client, site, h, "plan:pro", q="a") == ["a"]


def test_the_total_counts_the_filtered_rows(client, site, h, rows):
    r = client.get(f"/sites/{site.id}/feedback", params={"cf": ["plan:pro"]}, headers=h)
    assert r.json()["total"] == 2


@pytest.mark.parametrize("cf", ["nope:1", "plan", ":x", "Bad Id:x", "plan:", "beta:maybe"])
def test_a_bad_filter_is_a_422(client, site, h, rows, cf):
    r = client.get(f"/sites/{site.id}/feedback", params={"cf": cf}, headers=h)
    assert r.status_code == 422


def test_too_many_filters_are_refused(client, site, h):
    assert (
        client.get(f"/sites/{site.id}/feedback", params={"cf": ["plan:pro"] * 11}, headers=h).status_code
        == 422
    )


def test_the_cross_site_inbox_has_no_field_filters(client, site, h, rows):
    assert client.get("/inbox", params={"cf": "plan:pro"}, headers=h).status_code == 422
    assert client.get("/inbox", headers=h).status_code == 200


def read_csv(r):
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))


def test_the_export_has_a_column_per_field_after_the_fixed_ones(client, site, h, rows):
    r = client.get(f"/sites/{site.id}/feedback/export.csv", headers=h)
    header = r.content.decode("utf-8-sig").splitlines()[0].split(",")
    assert header[-3:] == ["Plan", "Beta tester", "Company"]
    assert header[:4] == ["id", "created_at", "status", "issue_type"]
    by_message = {row["message"]: row for row in read_csv(r)}
    assert (by_message["a"]["Plan"], by_message["a"]["Beta tester"], by_message["a"]["Company"]) == (
        "pro",
        "true",
        "Acme Corp",
    )
    assert by_message["b"]["Beta tester"] == "false"
    assert by_message["e"]["Plan"] == "" and by_message["e"]["Beta tester"] == ""
    assert '"plan"' in by_message["a"]["meta"], "the meta column still has everything"


def test_the_export_takes_the_same_filters_and_audits_only_which_fields(client, db, site, h, rows):
    r = client.get(
        f"/sites/{site.id}/feedback/export.csv", params={"cf": ["plan:pro", "company:acme"]}, headers=h
    )
    assert [row["message"] for row in read_csv(r)] == ["a"]
    event = db.query(AuditEvent).filter_by(action="feedback.export").one()
    assert event.details["fields"] == ["company", "plan"]
    assert "acme" not in str(event.details).lower()


def test_text_answers_that_look_like_formulas_are_neutralised_in_the_export(client, db, site, h):
    seed(db, site, "x", {"company": '=HYPERLINK("http://evil")'})
    assert read_csv(client.get(f"/sites/{site.id}/feedback/export.csv", headers=h))[0]["Company"].startswith(
        "'="
    )
