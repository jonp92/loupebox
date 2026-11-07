import io
import json
import os
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import delete, select

from app.core import retention
from app.core.attachments import ORPHAN_GRACE, sweep_orphans
from app.core.config import settings
from app.models import AuditEvent, Feedback, FeedbackAttachment, Role, User
from app.storage.backends.local import LocalStorage
from app.storage.registry import get_storage
from tests.conftest import SITE_ORIGIN, add_member, login, make_site, make_user, read_zip
from tests.test_challenge import pow_site

HEADERS = {"X-API-Key": "pk_test_Shop", "Origin": SITE_ORIGIN}


def image(fmt="PNG", size=(40, 30), **save) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, fmt, **save)
    return out.getvalue()


def send(client, files=(), payload=None, headers=None):
    """A multipart submission: the JSON `payload` part plus one `images` part per file."""
    parts = [("images", (f"shot{i}.png", data, "image/png")) for i, data in enumerate(files)]
    body = json.dumps(payload or {"message": "see the screenshot"})
    return client.post(
        "/feedback/with-images", data={"payload": body}, files=parts or None, headers=headers or HEADERS
    )


@pytest.fixture
def shop(db):
    return make_site(db, attachments_enabled=True)


def stored_keys() -> list[str]:
    return sorted(k for k, _ in get_storage().entries())


# --- storage backend -----------------------------------------------------------------------------


def test_local_storage_roundtrip_and_idempotent_delete():
    storage = LocalStorage()
    storage.put("site/a1", b"one")
    storage.put("site/a1", b"two")  # replaces
    assert storage.get("site/a1") == b"two"
    assert [k for k, _ in storage.entries()] == ["site/a1"]  # no temp file left behind
    storage.delete(["site/a1", "site/never-existed"])
    storage.delete(["site/a1"])
    with pytest.raises(FileNotFoundError):
        storage.get("site/a1")


@pytest.mark.parametrize(
    "key", ["../x", "a/../b", "/abs", "a//b", "a/.hidden", "a.b", "", "a/", "a\\b", "a\x00"]
)
def test_local_storage_refuses_keys_that_could_leave_the_folder(key):
    with pytest.raises(ValueError):
        LocalStorage().put(key, b"x")


def test_unknown_backend_is_an_error(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "nope")
    with pytest.raises(RuntimeError, match="storage backend"):
        get_storage()


# --- what the site accepts -----------------------------------------------------------------------


def test_config_says_whether_images_are_accepted(client, db):
    make_site(db)
    assert client.get("/feedback/config", headers=HEADERS).json() == {"attachments": {"enabled": False}}
    db.scalar(select(__import__("app.models", fromlist=["Site"]).Site)).attachments_enabled = True
    db.commit()
    cfg = client.get("/feedback/config", headers=HEADERS).json()["attachments"]
    assert cfg == {"enabled": True, "max_count": 3, "max_bytes": 5 * 1024 * 1024, "max_edge": 2048}


def test_config_needs_the_site_key_and_origin(client, shop):
    assert client.get("/feedback/config", headers={"Origin": SITE_ORIGIN}).status_code == 403
    assert client.get("/feedback/config", headers={"X-API-Key": "pk_test_Shop"}).status_code == 403


def test_images_are_refused_unless_the_site_opted_in(client, db):
    make_site(db)
    r = send(client, [image()])
    assert r.status_code == 403
    assert db.scalars(select(Feedback)).all() == [] and stored_keys() == []


def test_the_json_endpoint_is_unchanged_for_sites_with_images_on(client, shop, db):
    assert client.post("/feedback", json={"message": "plain"}, headers=HEADERS).status_code == 201
    assert db.scalar(select(FeedbackAttachment)) is None


# --- a submission with images --------------------------------------------------------------------


def test_submission_with_images_is_stored(client, db, shop):
    r = send(client, [image("PNG"), image("JPEG"), image("WEBP")])
    assert r.status_code == 201
    item = db.get(Feedback, uuid.UUID(r.json()["id"]))
    assert item.message == "see the screenshot" and item.attachment_count == 3
    rows = db.scalars(select(FeedbackAttachment).order_by(FeedbackAttachment.created_at)).all()
    assert sorted(a.content_type for a in rows) == ["image/jpeg", "image/png", "image/webp"]
    for a in rows:
        assert a.storage_key == f"{shop.id}/{a.id}" and a.site_id == shop.id
        data = get_storage().get(a.storage_key)
        assert a.size == len(data) and (a.width, a.height) == (40, 30)
    assert len(stored_keys()) == 3


def test_large_images_are_scaled_down_and_metadata_dropped(client, db, shop):
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    big = image("JPEG", (4000, 1000), exif=exif)
    assert b"SecretCameraMaker" in big
    assert send(client, [big]).status_code == 201
    a = db.scalar(select(FeedbackAttachment))
    assert (a.width, a.height) == (2048, 512)
    stored = get_storage().get(a.storage_key)
    assert b"SecretCameraMaker" not in stored and not Image.open(io.BytesIO(stored)).getexif()


def test_rotation_in_exif_is_applied_before_the_tag_is_dropped(client, db, shop):
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise when shown
    assert send(client, [image("JPEG", (60, 20), exif=exif)]).status_code == 201
    a = db.scalar(select(FeedbackAttachment))
    assert (a.width, a.height) == (20, 60)


@pytest.mark.parametrize(
    "blob",
    [
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"GIF89a" + b"\x00" * 40,
        b"%PDF-1.4 not an image",
        b"",
        b"\x89PNG\r\n\x1a\n" + b"garbage",  # right signature, no real image
        image("PNG")[:60],  # cut off
        image("GIF"),
    ],
)
def test_anything_that_is_not_a_png_jpeg_or_webp_is_refused(client, db, shop, blob):
    r = send(client, [image(), blob])
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "images", 1]
    assert db.scalars(select(Feedback)).all() == [] and stored_keys() == []  # all or nothing


def test_a_huge_but_tiny_file_is_refused_before_it_is_decoded(client, db, shop, monkeypatch):
    bomb = io.BytesIO()
    Image.new("L", (6000, 6000)).save(bomb, "PNG")  # 36 million pixels, tens of KB on the wire
    assert len(bomb.getvalue()) < 100_000
    r = send(client, [bomb.getvalue()])
    assert r.status_code == 422 and "too large" in r.json()["detail"][0]["msg"]
    assert stored_keys() == []


def test_a_file_over_the_byte_cap_is_refused(client, db, shop, monkeypatch):
    monkeypatch.setattr(settings, "attachment_max_bytes", 1024)
    noisy = os.urandom(3000)
    r = send(client, [noisy])
    assert r.status_code == 422 and "under" in r.json()["detail"][0]["msg"]


def test_a_request_over_the_total_cap_is_refused_unread(client, db, shop, monkeypatch):
    monkeypatch.setattr(settings, "attachment_max_count", 1)
    monkeypatch.setattr(settings, "attachment_max_bytes", 1024)
    r = send(client, [os.urandom(200_000)])
    assert r.status_code == 413 and db.scalars(select(Feedback)).all() == []


def test_too_many_images_are_refused(client, db, shop):
    r = send(client, [image()] * 4)
    assert r.status_code in (400, 413, 422) and db.scalars(select(Feedback)).all() == []


def test_the_payload_part_is_validated_like_the_json_endpoint(client, db, shop):
    assert send(client, [image()], payload={"message": ""}).json()["detail"][0]["loc"] == ["body", "message"]
    assert send(client, [image()], payload={"message": "x", "surprise": 1}).status_code == 422
    r = client.post(
        "/feedback/with-images",
        data={"nope": "x"},
        files=[("images", ("a.png", image(), "image/png"))],
        headers=HEADERS,
    )
    assert r.json()["detail"][0]["loc"] == ["body", "payload"]
    r = client.post("/feedback/with-images", data={"payload": "{not json"}, headers=HEADERS)
    assert r.status_code == 422


def test_the_usual_checks_still_apply(client, db, shop):
    assert send(client, [image()], headers={"Origin": SITE_ORIGIN}).status_code == 403  # no key
    assert send(client, [image()], headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403


def test_a_challenge_is_required_when_the_site_has_one(client, db):
    site = pow_site(db)
    site.attachments_enabled = True
    db.commit()
    assert send(client, [image()]).status_code == 403
    assert stored_keys() == []


def test_honeypot_stores_nothing(client, db, shop):
    r = send(client, [image()], payload={"message": "buy", "website": "http://spam"})
    assert r.status_code == 201 and db.scalars(select(Feedback)).all() == [] and stored_keys() == []


def test_spam_is_kept_without_its_images(client, db, shop):
    links = " ".join(f"http://x{i}.example" for i in range(10))
    assert send(client, [image()], payload={"message": links}).status_code == 201
    assert db.scalar(select(Feedback)).status.value == "spam" and stored_keys() == []


def test_a_duplicate_stores_no_second_set_of_images(client, db, shop):
    first = send(client, [image()])
    again = send(client, [image()])
    assert first.json() == again.json() and len(stored_keys()) == 1


def test_a_failed_write_leaves_nothing_behind(client, db, shop, monkeypatch):
    real, calls = LocalStorage.put, []

    def flaky(self, key, data, content_type="application/octet-stream"):
        calls.append(key)
        if len(calls) == 2:
            raise OSError("disk full")
        real(self, key, data, content_type)

    monkeypatch.setattr(LocalStorage, "put", flaky)
    with pytest.raises(OSError):
        send(client, [image(), image()])
    db.expire_all()
    assert db.scalars(select(Feedback)).all() == [] and stored_keys() == []


# --- reading them back ---------------------------------------------------------------------------


@pytest.fixture
def item(client, db, shop):
    r = send(client, [image("PNG", (50, 20)), image("JPEG")])
    fid = r.json()["id"]
    return shop, fid, db.scalars(select(FeedbackAttachment).order_by(FeedbackAttachment.created_at)).all()


def url(site, fid, aid=""):
    return f"/sites/{site.id}/feedback/{fid}/attachments" + (f"/{aid}" if aid else "")


def test_a_viewer_can_list_and_fetch_the_images(client, db, item):
    site, fid, rows = item
    add_member(db, make_user(db, "v@example.com"), site, Role.viewer)
    h = login(client, "v@example.com")
    listed = client.get(url(site, fid), headers=h).json()
    assert [a["id"] for a in listed] == [str(a.id) for a in rows]
    assert {"id", "content_type", "size", "width", "height", "created_at"} == set(listed[0])  # no storage key
    r = client.get(url(site, fid, rows[0].id), headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff" and "no-store" in r.headers["cache-control"]
    assert "sandbox" in r.headers["content-security-policy"]
    assert Image.open(io.BytesIO(r.content)).size == (50, 20)


def test_images_are_only_served_to_members_of_the_site(client, db, item):
    site, fid, rows = item
    make_user(db, "stranger@example.com")
    other = make_site(db, "Other")
    add_member(db, make_user(db, "o@example.com"), other, Role.admin)
    target = url(site, fid, rows[0].id)
    assert client.get(target).status_code == 401
    assert client.get(target, headers=login(client, "stranger@example.com")).status_code == 404
    # An admin of another site cannot reach it through their own site's path either.
    assert client.get(url(other, fid, rows[0].id), headers=login(client, "o@example.com")).status_code == 404


def test_an_image_of_another_item_is_not_served_under_this_one(client, db, item):
    site, _, rows = item
    add_member(db, make_user(db, "v@example.com"), site, Role.viewer)
    other_fid = client.post("/feedback", json={"message": "another"}, headers=HEADERS).json()["id"]
    h = login(client, "v@example.com")
    assert client.get(url(site, other_fid, rows[0].id), headers=h).status_code == 404


def test_a_missing_file_is_a_404_not_a_crash(client, db, item):
    site, fid, rows = item
    add_member(db, make_user(db, "v@example.com"), site, Role.viewer)
    get_storage().delete([rows[0].storage_key])
    assert client.get(url(site, fid, rows[0].id), headers=login(client, "v@example.com")).status_code == 404


def test_the_list_shows_how_many_images_each_item_has(client, db, item):
    site, _, _ = item
    add_member(db, make_user(db, "v@example.com"), site, Role.viewer)
    client.post("/feedback", json={"message": "no image"}, headers=HEADERS)
    page = client.get(f"/sites/{site.id}/feedback", headers=login(client, "v@example.com")).json()
    assert {i["message"]: i["attachment_count"] for i in page["items"]} == {
        "see the screenshot": 2,
        "no image": 0,
    }


def test_an_admin_can_remove_one_image_and_keep_the_message(client, db, item):
    site, fid, rows = item
    first, second = rows[0].id, rows[1].storage_key
    add_member(db, make_user(db, "e@example.com"), site, Role.editor)
    add_member(db, make_user(db, "a@example.com"), site, Role.admin)
    as_editor, as_admin = login(client, "e@example.com"), login(client, "a@example.com")
    assert client.delete(url(site, fid, first), headers=as_editor).status_code == 403
    assert client.delete(url(site, fid, first), headers=as_admin).status_code == 204
    assert stored_keys() == [second]
    db.expire_all()
    assert db.get(Feedback, uuid.UUID(fid)).attachment_count == 1
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "feedback.attachment_delete"))
    assert event.details == {"attachment_id": str(first)}


# --- files go when their feedback goes -----------------------------------------------------------


def test_deleting_an_item_deletes_its_files(client, db, item):
    site, fid, _ = item
    add_member(db, make_user(db, "a@example.com"), site, Role.admin)
    other = client.post(
        "/feedback/with-images",
        data={"payload": json.dumps({"message": "keep"})},
        files=[("images", ("k.png", image(), "image/png"))],
        headers=HEADERS,
    ).json()["id"]
    assert len(stored_keys()) == 3
    assert (
        client.delete(f"/sites/{site.id}/feedback/{fid}", headers=login(client, "a@example.com")).status_code
        == 204
    )
    assert len(stored_keys()) == 1
    assert uuid.UUID(other)


def test_bulk_delete_deletes_files(client, db, item):
    site, fid, _ = item
    add_member(db, make_user(db, "a@example.com"), site, Role.admin)
    r = client.post(
        f"/sites/{site.id}/feedback/bulk",
        json={"ids": [fid], "action": "delete"},
        headers=login(client, "a@example.com"),
    )
    assert r.status_code == 200 and stored_keys() == []


def test_retention_deletes_files(db, item):
    site, fid, _ = item
    db.get(Feedback, uuid.UUID(fid)).created_at = datetime.now(UTC) - timedelta(days=100)
    site.retention_delete_days = 30
    db.commit()
    assert retention.sweep(db, datetime.now(UTC)) == 1 and stored_keys() == []


def test_erasing_a_person_deletes_their_files(client, db, shop):
    for who in ("ann@example.com", "bob@example.com"):
        send(client, [image()], payload={"message": who, "email": who})
    add_member(db, make_user(db, "a@example.com"), shop, Role.admin)
    r = client.post(
        f"/sites/{shop.id}/privacy/erase",
        json={"email": "ANN@example.com"},
        headers=login(client, "a@example.com"),
    )
    assert r.json() == {"deleted": 1} and len(stored_keys()) == 1


def export(client, db, shop, email="ann@example.com"):
    if not db.scalar(select(User).where(User.email == "a@example.com")):
        add_member(db, make_user(db, "a@example.com"), shop, Role.admin)
    return client.post(
        f"/sites/{shop.id}/privacy/export", json={"email": email}, headers=login(client, "a@example.com")
    )


def test_the_person_export_is_a_zip_with_the_pictures(client, db, shop):
    first = send(
        client, [image("PNG"), image("JPEG")], payload={"message": "one", "email": "Ann@example.com"}
    )
    send(client, [image("WEBP")], payload={"message": "two", "email": "ann@example.com"})
    send(client, [image()], payload={"message": "not hers", "email": "bob@example.com"})
    r = export(client, db, shop)
    assert r.headers["content-type"] == "application/zip" and int(r.headers["content-length"]) == len(
        r.content
    )
    files = read_zip(r.content)
    data = json.loads(files["data.json"])
    assert [i["message"] for i in data["items"]] == ["one", "two"]
    paths = [img["file"] for item in data["items"] for img in item["images"]]
    fid = first.json()["id"]
    assert paths[:2] == [f"images/{fid}/1.png", f"images/{fid}/2.jpg"] and paths[2].endswith("/1.webp")
    assert sorted(files) == sorted(["data.json", *paths])  # nothing of Bob's
    for entry in (img for item in data["items"] for img in item["images"]):
        key = db.scalar(
            select(FeedbackAttachment.storage_key).where(FeedbackAttachment.id == uuid.UUID(entry["id"]))
        )
        assert files[entry["file"]] == get_storage().get(key) and entry["size"] == len(files[entry["file"]])
        assert "storage_key" not in entry and "note" not in entry


def test_pictures_are_stored_as_they_are_and_the_json_is_compressed(client, db, shop):
    send(client, [image()], payload={"message": "m", "email": "ann@example.com"})
    with zipfile.ZipFile(io.BytesIO(export(client, db, shop).content)) as zf:
        by_name = {i.filename: i.compress_type for i in zf.infolist()}
    assert by_name["data.json"] == zipfile.ZIP_DEFLATED
    assert [t for n, t in by_name.items() if n.startswith("images/")] == [zipfile.ZIP_STORED]


def test_a_picture_over_the_size_limit_is_listed_but_left_out(client, db, shop, monkeypatch):
    send(client, [image(size=(300, 300))], payload={"message": "m", "email": "ann@example.com"})
    monkeypatch.setattr(settings, "person_export_max_bytes", 10)
    files = read_zip(export(client, db, shop).content)
    assert list(files) == ["data.json"]
    (img,) = json.loads(files["data.json"])["items"][0]["images"]
    assert img["file"] is None and "size limit" in img["note"]


def test_a_missing_file_does_not_break_the_export(client, db, shop):
    send(client, [image(), image("JPEG")], payload={"message": "m", "email": "ann@example.com"})
    first = db.scalars(select(FeedbackAttachment).order_by(FeedbackAttachment.created_at)).first()
    get_storage().delete([first.storage_key])
    files = read_zip(export(client, db, shop).content)
    imgs = json.loads(files["data.json"])["items"][0]["images"]
    assert sorted(i["file"] is None for i in imgs) == [False, True]
    assert "missing" in next(i["note"] for i in imgs if i["file"] is None)
    assert len(files) == 2


def test_the_export_audit_counts_items_and_pictures_only(client, db, shop):
    send(client, [image(), image()], payload={"message": "m", "email": "ann@example.com"})
    export(client, db, shop)
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "privacy.export"))
    assert event.details == {"items": 1, "images": 2} and "ann" not in event.summary + str(event.details)


def test_deleting_a_site_deletes_its_files(client, db, item):
    site, _, _ = item
    make_user(db, "root@example.com", superadmin=True)
    assert client.delete(f"/sites/{site.id}", headers=login(client, "root@example.com")).status_code == 204
    assert stored_keys() == []


# --- the orphan sweep ----------------------------------------------------------------------------


def age(key, hours):
    path = LocalStorage().root / key
    old = (datetime.now(UTC) - timedelta(hours=hours)).timestamp()
    os.utime(path, (old, old))


def ours() -> str:
    return f"{uuid.uuid4()}/{uuid.uuid4()}"  # the shape of every key the app writes


def test_the_sweep_removes_only_old_files_nobody_refers_to(client, db, shop):
    send(client, [image()])
    (kept,) = stored_keys()
    storage = get_storage()
    old, young = ours(), ours()
    for key in (old, young, "_tmp/" + "a" * 32):
        storage.put(key, b"x")
    age(kept, 48)
    age(old, 2)
    age("_tmp/" + "a" * 32, 2)
    assert sweep_orphans(db, datetime.now(UTC)) == 2
    assert stored_keys() == sorted([kept, young])
    assert timedelta(hours=1) == ORPHAN_GRACE


def test_the_sweep_leaves_files_that_are_not_ours_alone(db):
    storage = get_storage()
    for key in ("someone-elses/report", "backups/2026/db"):
        storage.put(key, b"x")
        age(key, 48)
    assert sweep_orphans(db, datetime.now(UTC)) == 0
    assert stored_keys() == ["backups/2026/db", "someone-elses/report"]


def test_the_sweep_handles_more_files_than_one_chunk(db, monkeypatch):
    monkeypatch.setattr("app.core.attachments.CHUNK", 2)
    storage = get_storage()
    for _ in range(5):
        key = ours()
        storage.put(key, b"x")
        age(key, 2)
    assert sweep_orphans(db, datetime.now(UTC)) == 5 and stored_keys() == []


# --- the wire: CORS and size limits --------------------------------------------------------------


@pytest.mark.parametrize(
    "path,method", [("/feedback/with-images", "POST"), ("/feedback/config", "GET"), ("/feedback", "POST")]
)
def test_a_browser_on_an_allowed_site_may_call_the_image_paths(client, shop, path, method):
    r = client.options(
        path,
        headers={
            "Origin": SITE_ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "x-api-key",
        },
    )
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == SITE_ORIGIN
    assert method in r.headers["access-control-allow-methods"]
    denied = client.options(
        path, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": method}
    )
    assert denied.status_code == 403


def test_the_real_body_cap_stops_an_oversized_upload(client, shop):
    r = client.post(
        "/feedback/with-images", content=b"x" * (settings.attachment_request_bytes + 1), headers=HEADERS
    )
    assert r.status_code == 413 and r.json() == {"detail": "Request body too large"}


def test_an_upload_without_a_length_is_refused(client, shop):
    r = client.post(
        "/feedback/with-images",
        content=iter([b"x" * 10]),
        headers={**HEADERS, "Content-Type": "multipart/form-data; boundary=x"},
    )
    assert r.status_code == 411


def test_ordinary_submissions_keep_their_small_cap(client, shop):
    r = client.post("/feedback", content=b"x" * (settings.max_body_bytes + 1), headers=HEADERS)
    assert r.status_code == 413


def test_deleting_the_item_removes_the_rows_by_cascade(db, item):
    if db.get_bind().dialect.name == "sqlite":
        pytest.skip("SQLite does not enforce the foreign-key cascade")
    db.execute(delete(Feedback))
    db.commit()
    assert db.scalars(select(FeedbackAttachment)).all() == []


def test_an_animated_image_keeps_its_first_frame(client, db, shop):
    frames = [Image.new("RGB", (30, 20), c) for c in ((255, 0, 0), (0, 0, 255))]
    out = io.BytesIO()
    frames[0].save(out, "WEBP", save_all=True, append_images=frames[1:], duration=100, lossless=True)
    assert getattr(Image.open(io.BytesIO(out.getvalue())), "n_frames", 1) == 2
    assert send(client, [out.getvalue()]).status_code == 201
    stored = Image.open(io.BytesIO(get_storage().get(db.scalar(select(FeedbackAttachment)).storage_key)))
    r, _, blue = stored.convert("RGB").getpixel((0, 0))
    assert getattr(stored, "n_frames", 1) == 1 and r > 200 and blue < 60  # the red first frame, lossy
