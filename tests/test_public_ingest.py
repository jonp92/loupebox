from sqlalchemy import select

from app.core.config import settings
from app.models import Feedback, FeedbackStatus
from app.schemas.common import normalize_origin
from tests.conftest import SITE_ORIGIN, make_site

HEADERS = {"X-API-Key": "pk_test_Shop", "Origin": SITE_ORIGIN}


def post(client, body=None, headers=None):
    return client.post("/feedback", json=body or {"message": "Love it"}, headers=headers or HEADERS)


def test_accepts_valid_submission(client, db):
    make_site(db)
    r = post(client, {"message": "Love it", "rating": 5, "email": "A@B.com", "metadata": {"plan": "pro"}})
    assert r.status_code == 201
    row = db.scalar(select(Feedback))
    assert row.message == "Love it" and row.email == "a@b.com" and row.meta == {"plan": "pro"}
    assert row.status == FeedbackStatus.new
    assert len(row.ip_hash) == 32 and row.ip_hash != "testclient"


def test_rejects_missing_or_unknown_key(client, db):
    make_site(db)
    assert post(client, headers={"Origin": SITE_ORIGIN}).status_code == 403
    assert post(client, headers={"X-API-Key": "pk_nope", "Origin": SITE_ORIGIN}).status_code == 403


def test_rejects_wrong_or_missing_origin(client, db):
    make_site(db)
    assert (
        post(client, headers={"X-API-Key": "pk_test_Shop", "Origin": "https://evil.example"}).status_code
        == 403
    )
    assert post(client, headers={"X-API-Key": "pk_test_Shop"}).status_code == 403


def test_inactive_site_rejected(client, db):
    make_site(db, is_active=False)
    assert post(client).status_code == 403


def test_validation(client, db):
    make_site(db)
    assert post(client, {"message": "   "}).status_code == 422
    assert post(client, {"message": "x", "rating": 9}).status_code == 422
    assert post(client, {"message": "x", "unknown": 1}).status_code == 422
    assert post(client, {"message": "x", "page_url": "javascript:alert(1)"}).status_code == 422
    assert post(client, {"message": "x" * 5001}).status_code == 422
    assert post(client, {"message": "x", "metadata": {f"k{i}": 1 for i in range(21)}}).status_code == 422


def test_nul_bytes_stripped(client, db):
    make_site(db)
    assert post(client, {"message": "hi\x00there"}).status_code == 201
    assert db.scalar(select(Feedback)).message == "hithere"


def test_body_size_limit(client, db):
    make_site(db)
    r = client.post("/feedback", content=b"x" * (settings.max_body_bytes + 1), headers=HEADERS)
    assert r.status_code == 413


def test_honeypot_stores_nothing(client, db):
    make_site(db)
    assert post(client, {"message": "buy now", "website": "http://spam"}).status_code == 201
    assert db.scalar(select(Feedback)) is None


def test_duplicate_is_idempotent(client, db):
    make_site(db)
    a = post(client, {"message": "same"}).json()
    b = post(client, {"message": "Same"}).json()
    assert a == b
    assert len(db.scalars(select(Feedback)).all()) == 1


def test_link_heavy_message_quarantined(client, db):
    make_site(db)
    msg = " ".join(f"http://spam{i}.example" for i in range(5))
    assert post(client, {"message": msg}).status_code == 201
    assert db.scalar(select(Feedback)).status == FeedbackStatus.spam


def test_ip_rate_limit(client, db):
    make_site(db)
    codes = [post(client, {"message": f"m{i}"}).status_code for i in range(settings.public_ip_limit + 2)]
    assert codes[: settings.public_ip_limit] == [201] * settings.public_ip_limit
    assert codes[-1] == 429


def test_rate_limit_precedes_validation(client, db):
    make_site(db)
    for _ in range(settings.public_ip_limit):
        post(client, {"message": ""})  # 422s still count
    r = post(client, {"message": ""})
    assert r.status_code == 429 and "retry-after" in r.headers


def test_site_daily_limit(client, db):
    make_site(db, daily_limit=2)
    assert [post(client, {"message": f"m{i}"}).status_code for i in range(3)] == [201, 201, 429]


def test_cors_preflight_and_headers(client, db):
    make_site(db)
    pre = client.options(
        "/feedback",
        headers={
            "Origin": SITE_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key,content-type",
        },
    )
    assert pre.status_code == 204
    assert pre.headers["access-control-allow-origin"] == SITE_ORIGIN
    assert "access-control-allow-credentials" not in pre.headers

    bad = client.options(
        "/feedback",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert bad.status_code == 403

    r = post(client)
    assert r.headers["access-control-allow-origin"] == SITE_ORIGIN
    # Errors carry CORS headers too, so the widget can read them.
    err = post(client, headers={"X-API-Key": "pk_nope", "Origin": SITE_ORIGIN})
    assert err.status_code == 403 and err.headers["access-control-allow-origin"] == SITE_ORIGIN


def test_other_sites_origin_cannot_use_this_key(client, db):
    make_site(db, "Shop", origins=[SITE_ORIGIN])
    make_site(db, "Blog", origins=["https://blog.example.com"])
    r = post(client, headers={"X-API-Key": "pk_test_Shop", "Origin": "https://blog.example.com"})
    assert r.status_code == 403


def test_default_ports_are_dropped_from_origins():
    assert normalize_origin("HTTPS://Shop.example:443") == "https://shop.example"
    assert normalize_origin("http://shop.example:80/") == "http://shop.example"
    assert normalize_origin("https://shop.example:8443") == "https://shop.example:8443"
    assert normalize_origin("http://localhost:443") == "http://localhost:443"  # not the default for http
