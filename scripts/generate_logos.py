"""Render the app logos (SVG tiles and PNG icons) from the brand artwork in web/public/brand.

    python -m scripts.generate_logos

Needs `rsvg-convert` (macOS: brew install librsvg; Debian/Ubuntu: apt install librsvg2-bin).
The sources are web/public/brand/loupebox-icon-neon-dark.svg (the tiles) and loupebox-icon-neon-light.svg (the
favicon); see scripts/outline_brand.py for the brand files. Run this after changing them and commit the
generated files.
"""

import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "web" / "public"
DOCS_FAVICON = ROOT / "docs" / "assets" / "favicon.svg"
ART = PUBLIC / "brand" / "loupebox-icon-neon-dark.svg"  # square, opaque dark background
FAVICON_ART = PUBLIC / "brand" / "loupebox-icon-neon-light.svg"  # transparent, dark glyph
BACKGROUND = re.compile(r'<rect width="250" height="250" fill="#0B0E14"\s*/>')
ARTWORK_START = "<!-- Lens"  # everything from here on is the lens, check and handle
NOTE = "<!-- Generated from {} by scripts/generate_logos.py. Do not edit. -->\n"

TILE = "loupebox-icon.svg"  # rounded tile: PWA "any" icons and the email logo
FAVICON = "favicon.svg"  # transparent: a dark tile shows as a ring on the light plate Safari draws
MASKABLE = "loupebox-icon-maskable.svg"  # full-bleed with a safe zone, for maskable icons

# The README wordmarks are 800x250 with the dark one on an opaque background. The app wants them transparent
# and cropped to the artwork (measured: x 88-718, y 88-174, plus room for the neon glow).
WORDMARK_BACKGROUND = '  <rect width="800" height="250" fill="#0B0E14" />\n'
WORDMARK_VIEWBOX = ('viewBox="0 0 800 250"', 'viewBox="66 66 674 130"')

# The app header shows the wordmark at 28-44px high. 176px keeps it sharp up to 4x displays, as the fallback
# for browsers that can't use the SVG.
WORDMARK_PNG_HEIGHT = 176

ICO_SIZES = (16, 32, 48)  # favicon.ico, for browsers that ask for /favicon.ico by default

# (output file, source, size in px)
PNGS = [
    ("favicon-16.png", FAVICON, 16),  # <link rel="icon"> in index.html
    ("favicon-32.png", FAVICON, 32),
    ("icon-192.png", TILE, 192),  # PWA manifest, purpose "any"
    ("icon-512.png", TILE, 512),  # PWA manifest, purpose "any"
    ("icon-maskable-512.png", MASKABLE, 512),  # PWA manifest, purpose "maskable"
    # iOS rounds the corners itself and fills transparency with black, so it gets the square artwork.
    ("apple-touch-icon.png", "brand/loupebox-icon-neon-dark.svg", 180),
    # Emails: the admin UI serves this at PUBLIC_URL. 96px shows crisply at 48px on retina screens.
    ("email-logo.png", TILE, 96),
]


def derive(art: str) -> dict[str, str]:
    """The tile and maskable SVGs, derived from the artwork by text edits that fail if it changes."""
    if not BACKGROUND.search(art) or ARTWORK_START not in art:
        raise SystemExit(f"{ART.name} no longer has the expected background or artwork markers")
    head, art_body = art.split(ARTWORK_START, 1)
    art_body = ARTWORK_START + art_body.removesuffix("</svg>\n").removesuffix("</svg>")
    tile = BACKGROUND.sub(lambda m: m.group().replace("<rect ", '<rect rx="56" '), art)
    # The maskable safe zone is a central circle of 80% of the icon, so shrink the artwork inside it.
    shrink = f'<g transform="translate(125 125) scale(.8) translate(-125 -125)">\n{art_body}</g>\n</svg>\n'
    return {TILE: tile, MASKABLE: head + shrink}


def derive_wordmarks() -> dict[str, str]:
    """Transparent, cropped app wordmarks (brand/loupebox-wordmark-app-{light,dark}.svg), keyed by
    output name."""
    out = {}
    for variant in ("light", "dark"):
        art = (PUBLIC / "brand" / f"loupebox-wordmark-neon-{variant}.svg").read_text()
        if WORDMARK_VIEWBOX[0] not in art:
            raise SystemExit(f"loupebox-wordmark-neon-{variant}.svg no longer has the expected viewBox")
        out[f"brand/loupebox-wordmark-app-{variant}.svg"] = art.replace(WORDMARK_BACKGROUND, "").replace(
            *WORDMARK_VIEWBOX
        )
    return out


def render(source: str, height: int, width: int | None = None) -> bytes:
    """PNG bytes of an SVG under web/public; without a width it keeps the aspect ratio."""
    cmd = ["rsvg-convert", "-h", str(height)]
    if width:
        cmd += ["-w", str(width)]
    return subprocess.run([*cmd, str(PUBLIC / source)], check=True, capture_output=True).stdout


def ico(sizes: tuple[int, ...]) -> bytes:
    """A .ico holding one PNG per size (PNG-in-ICO is supported everywhere that still asks for .ico)."""
    images = [render(FAVICON, size, size) for size in sizes]
    offset = 6 + 16 * len(images)
    header, entries = struct.pack("<HHH", 0, 1, len(images)), b""
    for size, png in zip(sizes, images, strict=True):
        entries += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    return header + entries + b"".join(images)


def main() -> int:
    if not shutil.which("rsvg-convert"):
        print(
            "rsvg-convert not found. Install librsvg (brew install librsvg / apt install librsvg2-bin).",
            file=sys.stderr,
        )
        return 1
    generated = [
        (derive(ART.read_text()), f"brand/{ART.name}"),
        ({FAVICON: FAVICON_ART.read_text()}, f"brand/{FAVICON_ART.name}"),
        (derive_wordmarks(), "the brand wordmarks"),
    ]
    for svgs, source in generated:
        for name, svg in svgs.items():
            (PUBLIC / name).write_text(
                svg.replace("\n", "\n" + NOTE.format(source), 1)
            )  # the note goes under the <svg> line
            print(f"{name:24} generated")
    DOCS_FAVICON.write_text((PUBLIC / FAVICON).read_text())  # the docs site uses the same favicon
    print(f"{DOCS_FAVICON.relative_to(ROOT)} copied from {FAVICON}")
    for name, source, size in PNGS:
        (PUBLIC / name).write_bytes(render(source, size, size))
        print(f"{name:24} {size}x{size}  from {source}")
    for variant in ("light", "dark"):
        name = f"brand/loupebox-wordmark-app-{variant}.png"
        (PUBLIC / name).write_bytes(render(name.replace(".png", ".svg"), WORDMARK_PNG_HEIGHT))
        print(f"{name:24} {WORDMARK_PNG_HEIGHT}px high")
    (PUBLIC / "favicon.ico").write_bytes(ico(ICO_SIZES))
    print(f"{'favicon.ico':24} {', '.join(map(str, ICO_SIZES))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
