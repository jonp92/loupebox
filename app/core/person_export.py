"""The personal-data export: one zip with `data.json` and the image files the person sent.

The zip is built in a temporary file (in memory up to a few MB, then on disk) one image at a time, so a person
with many pictures never means many megabytes in the server's memory. Images are stored without compression
(they already are compressed) under names we make ourselves, so nothing from the upload ends up in a path.
"""

import json
import tempfile
import zipfile
from typing import IO

from fastapi.encoders import jsonable_encoder

from app.core.config import settings
from app.core.images import EXTENSIONS
from app.models import FeedbackAttachment
from app.storage.registry import get_storage

_SPOOL_BYTES = 8 * 1024 * 1024  # kept in memory up to this size, then spilled to disk


def image_path(attachment: FeedbackAttachment, number: int) -> str:
    return f"images/{attachment.feedback_id}/{number}.{EXTENSIONS[attachment.content_type]}"


def pack(data: dict, images: list[tuple[dict, FeedbackAttachment, str]]) -> tuple[IO[bytes], int]:
    """Zip `data` and the images. Each image is (its entry in `data`, its row, its path in the zip); the entry
    gets `file` (the path) or, when the file could not be included, `file: null` and a `note` saying why.
    Returns the open zip positioned at the start, and the number of images included."""
    budget = settings.person_export_max_bytes
    included = 0
    archive = tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES)  # noqa: SIM115  (closed by the caller)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry, attachment, path in images:
            entry["file"] = None
            if attachment.size > budget:
                entry["note"] = "left out: the export reached its size limit"
                continue
            try:
                blob = get_storage(attachment.storage).get(attachment.storage_key)
            except FileNotFoundError:
                entry["note"] = "left out: the file is missing from storage"
                continue
            budget -= len(blob)
            zf.writestr(path, blob, compress_type=zipfile.ZIP_STORED)
            entry["file"] = path
            included += 1
        zf.writestr("data.json", json.dumps(jsonable_encoder(data), ensure_ascii=False, indent=2))
    archive.seek(0)
    return archive, included
