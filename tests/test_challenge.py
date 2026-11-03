from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.challenges.registry import register_verifier
from app.challenges.replay import purge_expired
from app.challenges.verifiers import pow as pow_mod
from app.models import Feedback, Role, SiteStat, UsedChallenge
from tests.conftest import SITE_ORIGIN, add_member, login, make_site, make_user

HEADERS = {"X-API-Key": "pk_test_Shop", "Origin": SITE_ORIGIN}
BITS = 8  # a few hundred hashes: fast enough for tests


def pow_site(db, name="Shop", bits=BITS):
    return make_site(db, name, challenge_mode="pow", challenge_config={"bits": bits})


def fetch(client, headers=HEADERS):
    return client.post("/feedback/challenge", headers=headers)


def submit(client, proof=None, headers=HEADERS):
    body = {"message": "Love it"}
    if proof is not None:
        body["challenge"] = proof
    return client.post("/feedback", json=body, headers=headers)


def solved(client, headers=HEADERS):
    c = fetch(client, headers).json()
    return pow_mod.solve(c["token"], c["bits"])


def test_site_without_a_challenge_is_unchanged(client, db):
    make_site(db)
    assert fetch(client).json() == {"mode": "off"}
    assert submit(client).status_code == 201


def test_solve_and_submit(client, db):
    pow_site(db)
    c = fetch(client).json()
    assert c["mode"] == "pow" and c["bits"] == BITS and c["algorithm"] == "sha256"
    assert submit(client, pow_mod.solve(c["token"], c["bits"])).status_code == 201
    assert db.scalar(select(Feedback)) is not None


def test_missing_or_wrong_proof_is_rejected_and_counted(client, db):
    site = pow_site(db)
    r = submit(client)
    assert r.status_code == 403 and r.json()["detail"] == "Challenge required"
    c = fetch(client).json()
    assert submit(client, c["token"] + ":nonsense").status_code == 403
    assert submit(client, "garbage").status_code == 403
    assert submit(client, "x" * 2000).status_code == 422  # over the field length cap
    assert db.scalar(select(Feedback)) is None
    stat = db.scalar(select(SiteStat).where(SiteStat.site_id == site.id, SiteStat.kind == "challenge_failed"))
    assert stat.count == 3


def test_a_proof_works_only_once(client, db):
    pow_site(db)
    proof = solved(client)
    assert submit(client, proof).status_code == 201
    r = submit(client, proof)
    assert r.status_code == 403 and r.json()["detail"] == "Challenge failed"


def test_a_token_is_bound_to_its_site(client, db):
    pow_site(db, "Shop")
    other = pow_site(db, "Blog")
    other_headers = {"X-API-Key": other.public_key, "Origin": SITE_ORIGIN}
    assert submit(client, solved(client, other_headers)).status_code == 403


def test_tampered_or_expired_tokens_are_rejected(client, db, monkeypatch):
    pow_site(db)
    c = fetch(client).json()
    forged = c["token"][:-2] + ("AA" if not c["token"].endswith("AA") else "BB")
    assert submit(client, pow_mod.solve(forged, c["bits"])).status_code == 403

    proof = pow_mod.solve(c["token"], c["bits"])
    later = datetime.now(UTC) + timedelta(seconds=10_000)
    monkeypatch.setattr(pow_mod, "_now", lambda: later)
    assert submit(client, proof).status_code == 403


def test_raising_difficulty_invalidates_older_tokens(client, db):
    site = pow_site(db, bits=8)
    proof = solved(client)
    site.challenge_config = {"bits": 12}
    db.commit()
    assert submit(client, proof).status_code == 403


def test_unknown_mode_fails_closed(client, db):
    make_site(db, challenge_mode="ghost", challenge_config={})
    assert fetch(client).json() == {"mode": "off"}
    assert submit(client, "anything").status_code == 403


def test_challenge_endpoint_checks_key_and_origin(client, db):
    pow_site(db)
    assert fetch(client, {"X-API-Key": "nope", "Origin": SITE_ORIGIN}).status_code == 403
    assert fetch(client, {"X-API-Key": "pk_test_Shop", "Origin": "https://evil.example"}).status_code == 403
    assert fetch(client, {"X-API-Key": "pk_test_Shop"}).status_code == 403  # no Origin


def test_challenge_requests_do_not_eat_the_submission_budget(client, db):
    pow_site(db)
    for _ in range(15):  # past the 10/min submission limit per IP
        assert fetch(client).status_code == 200
    assert submit(client, solved(client)).status_code == 201


def test_challenge_endpoint_is_cors_enabled_for_site_origins(client, db):
    pow_site(db)
    r = client.options(
        "/feedback/challenge",
        headers={"Origin": SITE_ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-api-key"},
    )
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == SITE_ORIGIN
    assert "access-control-allow-credentials" not in r.headers


def test_expired_replay_markers_are_purged(db):
    now = datetime.now(UTC)
    db.add_all([UsedChallenge(id="old", expires_at=now - timedelta(minutes=1)), UsedChallenge(id="live", expires_at=now + timedelta(minutes=1))])
    db.commit()
    assert purge_expired(db, now) == 1
    assert [u.id for u in db.scalars(select(UsedChallenge))] == ["live"]


def test_registry_rejects_reserved_and_duplicate_keys():
    from app.challenges.base import ChallengeVerifier

    for key in ("off", "pow"):
        with pytest.raises(ValueError):
            register_verifier(type("V", (ChallengeVerifier,), {"key": key, "label": "x", "issue": lambda *a: {}, "verify": lambda *a: True}))


# --- admin settings -------------------------------------------------------------------------


def admin_headers(client, db, site, role=Role.admin):
    add_member(db, make_user(db, f"{role.value}@e.com"), site, role)
    return login(client, f"{role.value}@e.com")


def test_admin_enables_configures_and_disables_the_challenge(client, db):
    site = make_site(db)
    h = admin_headers(client, db, site)
    url = f"/sites/{site.id}"
    assert client.get(url, headers=h).json()["challenge_mode"] == "off"

    r = client.patch(url, json={"challenge_mode": "pow"}, headers=h).json()
    assert r["challenge_mode"] == "pow" and r["challenge_config"] == {"bits": 16}  # defaults filled in
    assert client.patch(url, json={"challenge_config": {"bits": 10}}, headers=h).json()["challenge_config"] == {"bits": 10}
    assert client.patch(url, json={"name": "Renamed"}, headers=h).json()["challenge_config"] == {"bits": 10}  # untouched
    assert client.patch(url, json={"challenge_mode": "off"}, headers=h).json()["challenge_config"] == {}


def test_challenge_settings_are_validated_and_admin_only(client, db):
    site = make_site(db)
    h = admin_headers(client, db, site)
    url = f"/sites/{site.id}"
    assert client.patch(url, json={"challenge_mode": "captcha9000"}, headers=h).status_code == 422
    assert client.patch(url, json={"challenge_mode": "pow", "challenge_config": {"bits": 99}}, headers=h).status_code == 422
    assert client.patch(url, json={"challenge_mode": "pow", "challenge_config": {"bits": "x"}}, headers=h).status_code == 422
    editor = admin_headers(client, db, site, Role.editor)
    assert client.patch(url, json={"challenge_mode": "pow"}, headers=editor).status_code == 403
    assert client.get(url, headers=h).json()["challenge_mode"] == "off"  # nothing half-applied


def test_stats_report_challenge_failures(client, db):
    site = pow_site(db)
    submit(client)
    h = admin_headers(client, db, site)
    today = client.get(f"/sites/{site.id}/stats", params={"days": 1}, headers=h).json()["days"][-1]
    assert today["challenge_failed"] == 1
