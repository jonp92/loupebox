"""The S3 backend against a real S3-protocol server (moto's, over HTTP), the way any S3-compatible provider
would be reached: an endpoint address, path-style addressing, listing across pages, bulk deletes."""

import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.exceptions import ClientError
from moto.server import ThreadedMotoServer
from PIL import Image
from sqlalchemy import delete, select, update

from app.core.attachments import StoredFile, delete_files, move_images, storage_counts, sweep_orphans
from app.core.config import settings
from app.db.session import get_sessionmaker
from app.models import AuditEvent, Feedback, FeedbackAttachment, Role
from app.storage.backends.s3 import S3Storage
from app.storage.base import StorageError
from app.storage.registry import backend_names, get_storage
from tests.conftest import add_member, login, make_user, read_zip
from tests.test_attachments import image, ours, send, shop  # noqa: F401  (shop is a fixture)


@pytest.fixture(scope="session")
def s3_server():
    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    _host, port = server.get_host_and_port()
    yield f"http://127.0.0.1:{port}"
    server.stop()


class Bucket:
    """A fresh bucket on the server, with the settings pointing at it and a client to look inside."""

    def __init__(self, endpoint: str):
        self.name = f"test-{uuid.uuid4().hex[:12]}"
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="us-east-1",
            aws_access_key_id="k",
            aws_secret_access_key="s",
        )
        self.client.create_bucket(Bucket=self.name)

    def objects(self) -> list[str]:
        pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=self.name)
        return sorted(o["Key"] for page in pages for o in page.get("Contents", []))

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.name, Key=key)["Body"].read()


@pytest.fixture
def bucket(s3_server, monkeypatch):
    b = Bucket(s3_server)
    for name, value in {
        "storage_backend": "s3",
        "s3_endpoint_url": s3_server,
        "s3_region": "us-east-1",
        "s3_bucket": b.name,
        "s3_access_key_id": "k",
        "s3_secret_access_key": "s",
        "s3_path_style": True,
        "s3_prefix": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    return b


def local_keys() -> list[str]:
    return sorted(k for k, _ in get_storage("local").entries())


# --- the backend itself --------------------------------------------------------------------------


def test_it_is_registered_next_to_the_local_one():
    assert backend_names() == ["local", "s3"]


def test_put_and_get_roundtrip_with_the_content_type(bucket):
    storage = get_storage()
    key = ours()
    storage.put(key, b"hello", "image/png")
    assert storage.get(key) == b"hello" and bucket.read(key) == b"hello"
    assert bucket.client.head_object(Bucket=bucket.name, Key=key)["ContentType"] == "image/png"
    storage.put(key, b"replaced")
    assert storage.get(key) == b"replaced"


def test_a_missing_key_is_a_file_not_found(bucket):
    with pytest.raises(FileNotFoundError):
        get_storage().get(ours())


def test_delete_ignores_what_is_already_gone(bucket):
    storage, key = get_storage(), ours()
    storage.put(key, b"x")
    storage.delete([key, ours()])
    storage.delete([key])
    assert bucket.objects() == []


def test_more_than_a_thousand_files_list_and_delete(bucket):
    storage = get_storage()
    keys = [ours() for _ in range(1005)]
    for k in keys:
        bucket.client.put_object(Bucket=bucket.name, Key=k, Body=b"x")
    listed = list(storage.entries())
    assert sorted(k for k, _ in listed) == sorted(keys)  # more than one page
    assert all(m.tzinfo is not None and abs(datetime.now(UTC) - m) < timedelta(minutes=5) for _, m in listed)
    storage.delete(keys)  # more than one delete request
    assert bucket.objects() == []


def test_a_folder_in_the_bucket_keeps_the_files_in_it_and_the_listing_stays_inside(bucket, monkeypatch):
    monkeypatch.setattr(settings, "s3_prefix", "/loupebox/images/")
    storage, key = get_storage(), ours()
    storage.put(key, b"mine")
    bucket.client.put_object(Bucket=bucket.name, Key="other/file", Body=b"not ours")
    assert bucket.objects() == sorted([f"loupebox/images/{key}", "other/file"])
    assert [k for k, _ in storage.entries()] == [key]
    assert storage.get(key) == b"mine"


@pytest.mark.parametrize("key", ["../x", "a/../b", "/abs", "a//b", "a.b", "", "a\\b"])
def test_keys_that_could_name_something_unexpected_are_refused(bucket, key):
    with pytest.raises(ValueError):
        get_storage().put(key, b"x")
    assert bucket.objects() == []


@pytest.mark.parametrize(
    "code", ["NotImplemented", "MalformedXML", "BadDigest", "InvalidDigest", "MissingContentMD5"]
)
def test_a_service_without_bulk_delete_falls_back_to_one_by_one_and_remembers(bucket, monkeypatch, code):
    from app.storage.backends import s3 as s3_module

    s3_module._one_by_one.clear()
    storage = get_storage()
    keys = [ours() for _ in range(3)]
    for k in keys:
        storage.put(k, b"x")
    batch_calls = []

    def refuses(**_):
        batch_calls.append(1)
        raise ClientError({"Error": {"Code": code, "Message": "no"}}, "DeleteObjects")

    monkeypatch.setattr(storage.client, "delete_objects", refuses)
    storage.delete(keys)
    assert bucket.objects() == []
    more = [ours() for _ in range(2)]
    for k in more:
        storage.put(k, b"x")
    storage.delete(more)  # goes straight to one-by-one: the batch call is not retried
    assert bucket.objects() == [] and len(batch_calls) == 1
    s3_module._one_by_one.clear()


def test_other_delete_errors_are_not_hidden(bucket, monkeypatch):
    storage = get_storage()

    def denied(**_):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "DeleteObjects")

    monkeypatch.setattr(storage.client, "delete_objects", denied)
    with pytest.raises(ClientError):
        storage.delete([ours()])


def test_the_client_is_reused_until_the_settings_change(bucket, monkeypatch):
    first = get_storage().client
    assert get_storage().client is first
    monkeypatch.setattr(settings, "s3_secret_access_key", "another")
    assert get_storage().client is not first


def test_checksums_are_only_sent_when_required(bucket):
    cfg = get_storage().client.meta.config
    assert cfg.request_checksum_calculation == "when_required"  # other providers reject the newer default
    assert cfg.response_checksum_validation == "when_required"


# --- setting it up: the connection check ---------------------------------------------------------


def test_it_is_not_configured_until_bucket_and_keys_are_set(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    storage = get_storage()
    assert storage.is_configured() is False
    with pytest.raises(StorageError, match="not fully set up"):
        storage.check()
    for name, value in {"s3_bucket": "b", "s3_access_key_id": "k", "s3_secret_access_key": "s"}.items():
        monkeypatch.setattr(settings, name, value)
    assert get_storage().is_configured() is True


def test_the_check_passes_against_a_working_bucket_and_leaves_nothing_behind(bucket):
    get_storage().check()
    assert bucket.objects() == []


def test_the_check_says_when_the_bucket_does_not_exist(bucket, monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", "no-such-bucket-here")
    with pytest.raises(StorageError, match="bucket does not exist"):
        get_storage().check()


def test_the_check_says_when_the_endpoint_cannot_be_reached(bucket, monkeypatch):
    monkeypatch.setattr(settings, "s3_endpoint_url", "http://127.0.0.1:9")
    with pytest.raises(StorageError, match="Could not reach the endpoint"):
        get_storage().check()


@pytest.mark.parametrize(
    "code,words",
    [
        ("InvalidAccessKeyId", "access key was not recognized"),
        ("SignatureDoesNotMatch", "secret key does not match"),
        ("AccessDenied", "Access denied"),
        ("AuthorizationHeaderMalformed", "region"),
        ("PermanentRedirect", "another region"),
        ("SomethingNew", "SomethingNew"),
    ],
)
def test_provider_errors_are_explained_in_plain_words(bucket, code, words):
    error = ClientError({"Error": {"Code": code, "Message": "secret details that stay out"}}, "PutObject")
    text = get_storage().explain(error)
    assert words in text and "secret details" not in text


def test_a_failed_check_never_includes_the_secret_key(bucket, monkeypatch):
    monkeypatch.setattr(settings, "s3_secret_access_key", "TOP-SECRET-VALUE")
    monkeypatch.setattr(settings, "s3_bucket", "no-such-bucket-here")
    with pytest.raises(StorageError) as raised:
        get_storage().check()
    assert "TOP-SECRET-VALUE" not in str(raised.value)


# --- images stored in a bucket -------------------------------------------------------------------


def row_storage(db) -> list[str]:
    db.expire_all()
    return sorted(db.scalars(select(FeedbackAttachment.storage)))


def test_an_image_goes_to_the_bucket_and_comes_back_through_the_authenticated_route(client, db, shop, bucket):
    r = send(client, [image("PNG", (50, 20))])
    assert r.status_code == 201
    (att,) = db.scalars(select(FeedbackAttachment)).all()
    assert att.storage == "s3" and bucket.objects() == [att.storage_key] and local_keys() == []
    assert bucket.client.head_object(Bucket=bucket.name, Key=att.storage_key)["ContentType"] == "image/png"
    add_member(db, make_user(db, "v@example.com"), shop, Role.viewer)
    got = client.get(
        f"/sites/{shop.id}/feedback/{r.json()['id']}/attachments/{att.id}",
        headers=login(client, "v@example.com"),
    )
    assert got.status_code == 200 and Image.open(io.BytesIO(got.content)).size == (50, 20)


def test_images_are_not_offered_while_the_bucket_is_not_set_up(client, db, shop, monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")  # no bucket or keys
    assert client.get(
        "/feedback/config", headers={"X-API-Key": "pk_test_Shop", "Origin": "https://shop.example.com"}
    ).json()["attachments"] == {"enabled": False}
    r = send(client, [image()])
    assert r.status_code == 503 and db.scalars(select(Feedback)).all() == []


def test_the_site_settings_say_whether_the_storage_is_ready(client, db, shop, monkeypatch):
    add_member(db, make_user(db, "a@example.com"), shop, Role.admin)
    h = login(client, "a@example.com")
    assert client.get(f"/sites/{shop.id}", headers=h).json()["attachments_ready"] is True
    monkeypatch.setattr(settings, "storage_backend", "s3")
    assert client.get(f"/sites/{shop.id}", headers=h).json()["attachments_ready"] is False


def test_a_failed_upload_to_the_bucket_leaves_nothing_behind(client, db, shop, bucket, monkeypatch):
    real, calls = get_storage().client.put_object, []

    def flaky(**kw):
        calls.append(kw["Key"])
        if len(calls) == 2:
            raise ClientError({"Error": {"Code": "InternalError", "Message": "x"}}, "PutObject")
        return real(**kw)

    monkeypatch.setattr(get_storage().client, "put_object", flaky)
    with pytest.raises(ClientError):
        send(client, [image(), image()])
    db.expire_all()
    assert db.scalars(select(Feedback)).all() == [] and bucket.objects() == []


def test_every_delete_path_removes_the_objects_from_the_bucket(client, db, shop, bucket):
    add_member(db, make_user(db, "a@example.com"), shop, Role.admin)
    h = login(client, "a@example.com")
    ids = [
        send(client, [image()], payload={"message": f"m{i}", "email": f"p{i}@example.com"}).json()["id"]
        for i in range(4)
    ]
    assert len(bucket.objects()) == 4
    assert client.delete(f"/sites/{shop.id}/feedback/{ids[0]}", headers=h).status_code == 204
    assert len(bucket.objects()) == 3
    bulk = client.post(
        f"/sites/{shop.id}/feedback/bulk", json={"ids": [ids[1]], "action": "delete"}, headers=h
    )
    assert bulk.status_code == 200 and len(bucket.objects()) == 2
    erase = client.post(f"/sites/{shop.id}/privacy/erase", json={"email": "p2@example.com"}, headers=h)
    assert erase.json() == {"deleted": 1} and len(bucket.objects()) == 1
    att = db.scalar(select(FeedbackAttachment).where(FeedbackAttachment.feedback_id == uuid.UUID(ids[3])))
    assert (
        client.delete(f"/sites/{shop.id}/feedback/{ids[3]}/attachments/{att.id}", headers=h).status_code
        == 204
    )
    assert bucket.objects() == []


def test_the_person_export_zip_includes_pictures_held_in_the_bucket(client, db, shop, bucket):
    send(client, [image("PNG"), image("JPEG")], payload={"message": "m", "email": "ann@example.com"})
    add_member(db, make_user(db, "a@example.com"), shop, Role.admin)
    r = client.post(
        f"/sites/{shop.id}/privacy/export",
        json={"email": "ann@example.com"},
        headers=login(client, "a@example.com"),
    )
    files = read_zip(r.content)
    assert sorted(n.rsplit(".", 1)[-1] for n in files if n.startswith("images/")) == ["jpg", "png"]


# --- changing storage: old files stay reachable, and can be moved -------------------------------


def test_images_stored_before_the_switch_stay_served_and_deletable(client, db, shop, monkeypatch, s3_server):
    first = send(client, [image()], payload={"message": "old"}).json()["id"]  # local storage
    b = Bucket(s3_server)
    for name, value in {
        "storage_backend": "s3",
        "s3_endpoint_url": s3_server,
        "s3_bucket": b.name,
        "s3_access_key_id": "k",
        "s3_secret_access_key": "s",
        "s3_path_style": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    second = send(client, [image()], payload={"message": "new"}).json()["id"]  # now in the bucket
    assert row_storage(db) == ["local", "s3"] and len(local_keys()) == 1 and len(b.objects()) == 1
    add_member(db, make_user(db, "a@example.com"), shop, Role.admin)
    h = login(client, "a@example.com")
    for fid in (first, second):  # both are served
        (a,) = [a for a in client.get(f"/sites/{shop.id}/feedback/{fid}/attachments", headers=h).json()]
        assert (
            client.get(f"/sites/{shop.id}/feedback/{fid}/attachments/{a['id']}", headers=h).status_code == 200
        )
    client.delete(
        f"/sites/{shop.id}/feedback/{first}", headers=h
    )  # the old one is removed from the old place
    assert local_keys() == [] and len(b.objects()) == 1


def mixed(client, db, monkeypatch, s3_server, count=3):
    """`count` images on local disk, then the storage switched to a bucket."""
    for i in range(count):
        send(client, [image()], payload={"message": f"m{i}"})
    b = Bucket(s3_server)
    for name, value in {
        "storage_backend": "s3",
        "s3_endpoint_url": s3_server,
        "s3_bucket": b.name,
        "s3_access_key_id": "k",
        "s3_secret_access_key": "s",
        "s3_path_style": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    return b


def test_moving_copies_the_files_updates_the_rows_and_removes_the_old_ones(
    client, db, shop, monkeypatch, s3_server
):
    b = mixed(client, db, monkeypatch, s3_server, 3)
    before = {
        a.storage_key: get_storage("local").get(a.storage_key) for a in db.scalars(select(FeedbackAttachment))
    }
    result = move_images(db, "s3", limit=2)
    assert (result.moved, result.failed, result.remaining) == (2, 0, 1)
    result = move_images(db, "s3", limit=10)
    assert (result.moved, result.remaining) == (1, 0)
    assert row_storage(db) == ["s3"] * 3 and local_keys() == []
    assert {k: b.read(k) for k in b.objects()} == before  # identical bytes
    assert storage_counts(db) == {"s3": 3}
    assert move_images(db, "s3", limit=10).moved == 0  # nothing left: safe to repeat


def test_a_file_that_is_already_gone_does_not_block_the_rest(client, db, shop, monkeypatch, s3_server):
    b = mixed(client, db, monkeypatch, s3_server, 3)
    first = db.scalars(select(FeedbackAttachment).order_by(FeedbackAttachment.created_at)).first()
    get_storage("local").delete([first.storage_key])
    result = move_images(db, "s3", limit=10)
    assert (result.moved, result.missing, result.remaining) == (2, 1, 0)
    assert len(b.objects()) == 2 and row_storage(db) == ["s3"] * 3


def test_a_failing_destination_keeps_the_files_where_they_are_and_says_why(
    client, db, shop, monkeypatch, s3_server
):
    mixed(client, db, monkeypatch, s3_server, 2)
    monkeypatch.setattr(settings, "s3_bucket", "no-such-bucket-here")
    result = move_images(db, "s3", limit=10)
    assert (result.moved, result.failed, result.remaining) == (0, 2, 2)
    assert "bucket does not exist" in result.error
    assert row_storage(db) == ["local", "local"] and len(local_keys()) == 2


def test_a_row_deleted_while_its_file_is_copied_leaves_no_copy_behind(
    client, db, shop, monkeypatch, s3_server
):
    b = mixed(client, db, monkeypatch, s3_server, 1)
    real_put = S3Storage.put

    def put_then_the_row_vanishes(self, key, data, content_type="application/octet-stream"):
        real_put(self, key, data, content_type)
        with get_sessionmaker()() as other:  # someone deletes the feedback in the middle of the move
            other.execute(delete(FeedbackAttachment))
            other.commit()

    monkeypatch.setattr(S3Storage, "put", put_then_the_row_vanishes)
    result = move_images(db, "s3", limit=10)
    assert result.moved == 0 and b.objects() == [], "the copy made for a deleted row is removed again"
    assert len(local_keys()) == 1, "the old file is left for whoever deleted the row (or the sweep)"


def test_the_sweep_cleans_every_storage_that_holds_images_and_ignores_foreign_objects(
    client, db, shop, monkeypatch, s3_server
):
    b = mixed(client, db, monkeypatch, s3_server, 1)
    old_local, old_s3 = ours(), ours()
    get_storage("local").put(old_local, b"x")
    get_storage("s3").put(old_s3, b"x")
    b.client.put_object(Bucket=b.name, Key="someone-elses/object", Body=b"keep me")
    import os

    stamp = (datetime.now(UTC) - timedelta(hours=3)).timestamp()
    os.utime(get_storage("local").root / old_local, (stamp, stamp))
    # The bucket's own clock is the server's: backdate through the sweep's notion of "now".
    removed = sweep_orphans(db, datetime.now(UTC) + timedelta(hours=3))
    assert removed >= 2  # both strays, in both places
    assert (
        "someone-elses/object" in b.objects() and old_s3 not in b.objects() and old_local not in local_keys()
    )
    (att,) = db.scalars(select(FeedbackAttachment)).all()  # the real image's file is still there
    assert get_storage(att.storage).get(att.storage_key)


def test_delete_files_groups_by_storage_and_survives_a_failing_one(bucket, caplog):
    local_key, s3_key = ours(), ours()
    get_storage("local").put(local_key, b"x")
    get_storage("s3").put(s3_key, b"x")
    delete_files([StoredFile("local", local_key), StoredFile("s3", s3_key), StoredFile("nope", ours())])
    assert local_keys() == [] and bucket.objects() == []
    assert "could not delete" in caplog.text  # the unknown backend failed, and was only logged


def test_a_move_is_audited_by_the_system_endpoints_with_counts_only(client, db, shop, monkeypatch, s3_server):
    mixed(client, db, monkeypatch, s3_server, 2)
    make_user(db, "root@example.com", superadmin=True)
    h = login(client, "root@example.com")
    r = client.post("/system/storage/move", headers=h)
    assert r.json() == {"moved": 2, "missing": 0, "failed": 0, "remaining": 0, "error": None}
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "storage.move"))
    assert event.details == {"to": "s3", "moved": 2, "missing": 0, "failed": 0}


def test_a_row_another_mover_already_switched_is_left_alone(client, db, shop, monkeypatch, s3_server):
    """Two movers at once: the loser must not count it, delete anything, or undo the other."""
    b = mixed(client, db, monkeypatch, s3_server, 1)
    real_put = S3Storage.put

    def put_while_the_other_mover_finishes(self, key, data, content_type="application/octet-stream"):
        real_put(self, key, data, content_type)
        with get_sessionmaker()() as other:  # the other mover switched the row (and will remove the old file)
            other.execute(update(FeedbackAttachment).values(storage="s3"))
            other.commit()

    monkeypatch.setattr(S3Storage, "put", put_while_the_other_mover_finishes)
    result = move_images(db, "s3", limit=10)
    assert result.moved == 0, "the other mover did the work"
    assert len(b.objects()) == 1, "the copy the row now points at is not deleted"
    assert len(local_keys()) == 1, "and the old file is left to the mover that switched the row"


def test_the_person_export_includes_pictures_still_in_another_storage(
    client, db, shop, monkeypatch, s3_server
):
    send(client, [image("PNG")], payload={"message": "m", "email": "ann@example.com"})  # on local disk
    mixed_bucket = Bucket(s3_server)
    for name, value in {
        "storage_backend": "s3",
        "s3_endpoint_url": s3_server,
        "s3_bucket": mixed_bucket.name,
        "s3_access_key_id": "k",
        "s3_secret_access_key": "s",
        "s3_path_style": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    send(client, [image("JPEG")], payload={"message": "n", "email": "ann@example.com"})  # in the bucket
    add_member(db, make_user(db, "a@example.com"), shop, Role.admin)
    r = client.post(
        f"/sites/{shop.id}/privacy/export",
        json={"email": "ann@example.com"},
        headers=login(client, "a@example.com"),
    )
    files = read_zip(r.content)
    assert sorted(n.rsplit(".", 1)[-1] for n in files if n.startswith("images/")) == ["jpg", "png"]
    data = json.loads(files["data.json"])
    assert all("note" not in i for item in data["items"] for i in item["images"])
