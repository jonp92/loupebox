"""Setting up image storage from the admin UI: the settings, the connection check, and moving old images."""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import AppSetting, AuditEvent
from app.storage.registry import get_storage
from tests.conftest import login, make_user
from tests.test_attachments import image, send, shop  # noqa: F401  (shop is a fixture)
from tests.test_s3_storage import Bucket, bucket, s3_server  # noqa: F401  (fixtures)


@pytest.fixture
def h(client, db):
    make_user(db, "root@example.com", superadmin=True)
    return login(client, "root@example.com")


def by_key(items):
    return {s["key"]: s for s in items}


def patch(client, h, **changes):
    return client.patch("/settings", json={"changes": changes}, headers=h)


S3_SETTINGS = (
    "s3_endpoint_url",
    "s3_region",
    "s3_bucket",
    "s3_access_key_id",
    "s3_secret_access_key",
    "s3_path_style",
    "s3_prefix",
)


# --- who may use it ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [("get", "/system/storage"), ("post", "/system/test-storage"), ("post", "/system/storage/move")],
)
def test_only_superadmins_can_use_the_storage_endpoints(client, db, method, path):
    assert getattr(client, method)(path).status_code == 401
    make_user(db, "plain@example.com")
    assert getattr(client, method)(path, headers=login(client, "plain@example.com")).status_code == 403


# --- the settings --------------------------------------------------------------------------------


def test_the_storage_settings_are_listed_with_their_choices_and_when_they_apply(client, h):
    items = by_key(client.get("/settings", headers=h).json())
    assert items["storage_backend"]["choices"] == ["local", "s3"]
    assert items["storage_backend"]["group"] == "Image storage" and items["storage_backend"]["editable"]
    assert items["storage_backend"]["show_when"] is None
    for key in S3_SETTINGS:
        assert items[key]["group"] == "Image storage" and items[key]["editable"]
        assert items[key]["show_when"] == {"key": "storage_backend", "value": "s3"}, key
    assert items["s3_path_style"]["type"] == "boolean"
    folder = items["attachments_dir"]
    assert folder["group"] == "Image storage" and folder["editable"]
    assert folder["show_when"] == {"key": "storage_backend", "value": "local"}


def test_the_image_limits_are_shown_but_set_in_the_env(client, h):
    items = by_key(client.get("/settings", headers=h).json())
    for key in (
        "attachment_max_count",
        "attachment_max_bytes",
        "attachment_max_edge",
        "attachment_max_pixels",
    ):
        assert items[key]["group"] == "Server" and not items[key]["editable"], key
    assert patch(client, h, attachment_max_count=3).status_code == 422


def test_the_images_folder_can_be_changed_and_new_images_go_there(client, h, tmp_path):
    folder = tmp_path / "elsewhere"
    assert patch(client, h, attachments_dir=str(folder)).status_code == 200
    assert settings.attachments_dir == str(folder)
    get_storage("local").put("abc/def", b"x")
    assert (folder / "abc" / "def").read_bytes() == b"x"
    for bad in ("", "a;b", "x" * 201):
        r = patch(client, h, attachments_dir=bad)
        assert r.status_code == 422, bad
        assert "must be a folder path" in r.json()["detail"] and "pattern" not in r.json()["detail"], bad


def test_saving_the_storage_takes_effect_at_once(client, h):
    r = patch(
        client,
        h,
        storage_backend="s3",
        s3_endpoint_url="http://minio:9000",
        s3_region="eu-west-1",
        s3_bucket="loupebox-images",
        s3_access_key_id="AKIAEXAMPLE",
        s3_path_style=True,
        s3_prefix="prod/img",
    )
    assert r.status_code == 200, r.text
    assert (settings.storage_backend, settings.s3_bucket, settings.s3_path_style) == (
        "s3",
        "loupebox-images",
        True,
    )
    assert get_storage().key == "s3" and get_storage().prefix == "prod/img/"


def test_the_secret_key_is_write_only_and_stored_encrypted(client, h, db):
    before = by_key(client.get("/settings", headers=h).json())["s3_secret_access_key"]
    assert before["secret"] and before["configured"] is False
    r = patch(client, h, s3_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    assert r.status_code == 200
    item = by_key(r.json())["s3_secret_access_key"]
    assert item["configured"] is True and item["value"] is None and item["env_value"] is None
    assert "wJalrXUtnFEMI" not in r.text and "wJalrXUtnFEMI" not in client.get("/settings", headers=h).text
    stored = db.scalar(select(AppSetting).where(AppSetting.key == "s3_secret_access_key")).value
    assert "wJalrXUtnFEMI" not in str(stored)
    assert (
        settings.s3_secret_access_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    )  # what the backend uses
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "settings.update"))
    assert "wJalrXUtnFEMI" not in str(event.details) and event.details == {"s3_secret_access_key": "changed"}


@pytest.mark.parametrize(
    "key,value",
    [
        ("storage_backend", "gcs"),
        ("s3_endpoint_url", "ftp://minio:9000"),
        ("s3_endpoint_url", "https://user:password@minio.example.com"),  # no credentials in an address
        ("s3_endpoint_url", "minio:9000"),
        ("s3_endpoint_url", "https://a b.example.com"),
        ("s3_region", "us east 1"),
        ("s3_bucket", "../bucket"),
        ("s3_bucket", "-leading-dash"),
        ("s3_access_key_id", "has space"),
        ("s3_prefix", "has space/and..?"),
    ],
)
def test_a_bad_value_is_refused_and_nothing_is_saved(client, h, key, value):
    r = patch(client, h, **{key: value})
    assert r.status_code == 422, r.text
    assert getattr(settings, key) != value


@pytest.mark.parametrize(
    "key,value",
    [
        ("s3_endpoint_url", "https://abc123.r2.cloudflarestorage.com"),
        ("s3_endpoint_url", "http://127.0.0.1:9000"),
        ("s3_endpoint_url", "https://s3.us-west-004.backblazeb2.com/"),
        ("s3_endpoint_url", ""),
        ("s3_region", "auto"),
        ("s3_bucket", "my.bucket-name_1"),
        ("s3_prefix", "a/b-c_d.e"),
    ],
)
def test_the_usual_provider_values_are_accepted(client, h, key, value):
    assert patch(client, h, **{key: value}).status_code == 200


def test_resetting_goes_back_to_the_env_value(client, h):
    patch(client, h, storage_backend="s3")
    assert patch(client, h, storage_backend=None).status_code == 200
    assert settings.storage_backend == "local"


# --- status and the connection check ------------------------------------------------------------


def test_status_with_the_default_local_storage(client, h):
    assert client.get("/system/storage", headers=h).json() == {
        "backend": "local",
        "configured": True,
        "counts": {},
        "to_move": 0,
    }


def test_status_counts_images_by_where_they_are(client, h, db, shop, monkeypatch):
    send(client, [image(), image()])
    monkeypatch.setattr(settings, "storage_backend", "s3")  # chosen, but nothing filled in yet
    assert client.get("/system/storage", headers=h).json() == {
        "backend": "s3",
        "configured": False,
        "counts": {"local": 2},
        "to_move": 2,
    }


def test_the_check_passes_for_local_storage(client, h):
    assert client.post("/system/test-storage", headers=h).json() == {
        "status": "ok",
        "backend": "local",
        "error": None,
    }


def test_the_check_explains_an_incomplete_setup(client, h, monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    r = client.post("/system/test-storage", headers=h).json()
    assert r["status"] == "failed" and r["backend"] == "s3" and "not fully set up" in r["error"]


def test_the_check_passes_against_a_working_bucket(client, h, bucket):
    assert client.post("/system/test-storage", headers=h).json()["status"] == "ok"
    assert bucket.objects() == []


def test_the_check_names_the_problem_and_never_the_secret(client, h, bucket, monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", "no-such-bucket-here")
    monkeypatch.setattr(settings, "s3_secret_access_key", "TOP-SECRET-VALUE")
    r = client.post("/system/test-storage", headers=h)
    assert r.json()["status"] == "failed" and "bucket does not exist" in r.json()["error"]
    assert "TOP-SECRET-VALUE" not in r.text


def test_the_check_can_be_tried_a_few_times_but_not_endlessly(client, h):
    codes = [client.post("/system/test-storage", headers=h).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and 429 in codes[10:]


# --- moving what is already stored --------------------------------------------------------------


def test_moving_needs_the_new_storage_to_be_set_up(client, h, monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    assert client.post("/system/storage/move", headers=h).status_code == 409


def test_moving_works_through_the_images_a_few_at_a_time(client, h, db, shop, monkeypatch, s3_server):
    monkeypatch.setattr(settings, "public_ip_limit", 1000)  # twelve submissions from one visitor
    for i in range(12):
        send(client, [image()], payload={"message": f"m{i}"})
    target = Bucket(s3_server)
    for name, value in {
        "storage_backend": "s3",
        "s3_endpoint_url": s3_server,
        "s3_bucket": target.name,
        "s3_access_key_id": "k",
        "s3_secret_access_key": "s",
        "s3_path_style": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    assert client.get("/system/storage", headers=h).json()["to_move"] == 12
    first = client.post("/system/storage/move", headers=h).json()
    assert first == {"moved": 10, "missing": 0, "failed": 0, "remaining": 2, "error": None}
    second = client.post("/system/storage/move", headers=h).json()
    assert second == {"moved": 2, "missing": 0, "failed": 0, "remaining": 0, "error": None}
    assert len(target.objects()) == 12 and client.get("/system/storage", headers=h).json() == {
        "backend": "s3",
        "configured": True,
        "counts": {"s3": 12},
        "to_move": 0,
    }
    assert (
        client.post("/system/storage/move", headers=h).json()["moved"] == 0
    )  # nothing left, and nothing is audited
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "storage.move")).all()
    assert [e.details["moved"] for e in events] == [10, 2]


def test_a_move_that_cannot_write_reports_why_and_changes_nothing(client, h, db, shop, bucket, monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "local")
    send(client, [image()])
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "no-such-bucket-here")
    r = client.post("/system/storage/move", headers=h).json()
    assert (r["moved"], r["failed"], r["remaining"]) == (0, 1, 1) and "bucket does not exist" in r["error"]
