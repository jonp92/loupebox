"""Turn an uploaded image into one we are willing to store: decoded, scaled down and written out afresh.

Re-encoding is the defense: whatever the upload really was (a polyglot, an image with a payload after the
pixels, an SVG renamed .png) only decoded pixels in PNG, JPEG or WebP survive. Metadata (EXIF location,
camera, embedded text) is not copied.
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class ImageRejected(ValueError):
    """The message is safe to show to the visitor."""


@dataclass(frozen=True)
class StoredImage:
    data: bytes
    content_type: str
    width: int
    height: int


def process_image(raw: bytes) -> StoredImage:
    try:
        img = Image.open(io.BytesIO(raw), formats=list(FORMATS))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImageRejected("Only PNG, JPEG and WebP images are accepted") from None
    fmt = img.format or ""
    if img.width * img.height > settings.attachment_max_pixels:  # header only: nothing is decoded yet
        raise ImageRejected("The image is too large")
    try:
        img = ImageOps.exif_transpose(img)  # also loads the first frame of an animation
        img.thumbnail((settings.attachment_max_edge, settings.attachment_max_edge), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        if fmt == "JPEG":
            img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
        elif fmt == "PNG":
            img.save(out, "PNG", optimize=True)
        else:
            img.save(out, "WEBP", quality=85)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):  # truncated or corrupt data
        raise ImageRejected("The image could not be read") from None
    return StoredImage(out.getvalue(), FORMATS[fmt], img.width, img.height)
