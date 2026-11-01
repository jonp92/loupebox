from urllib.parse import urlsplit


def clean_text(value: str | None) -> str | None:
    """Strip NUL bytes (rejected by Postgres) and surrounding whitespace."""
    if value is None:
        return None
    value = value.replace("\x00", "").strip()
    return value or None


def normalize_origin(origin: str) -> str:
    """Return scheme://host[:port] in lowercase, or raise ValueError."""
    parts = urlsplit(origin.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Invalid origin: {origin!r}")
    if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username:
        raise ValueError(f"Origin must be scheme://host[:port] only: {origin!r}")
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname.lower()}{port}"


def sniff_image(raw: bytes) -> str | None:
    """Return the image MIME type from magic bytes (PNG/JPEG/WebP only; never SVG, which can carry script)."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None
