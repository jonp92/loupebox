"""Render the app logos (SVG tiles and PNG icons) from the brand artwork in web/public/brand.

    python -m scripts.generate_logos

Needs `rsvg-convert` (macOS: brew install librsvg; Debian/Ubuntu: apt install librsvg2-bin).
The only source is web/public/brand/loupebox-icon-neon-dark.svg (see scripts/outline_brand.py for the brand
files). Run this after changing it and commit the generated files.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "web" / "public"
ART = PUBLIC / "brand" / "loupebox-icon-neon-dark.svg"  # square, opaque dark background
BACKGROUND = re.compile(r'<rect width="250" height="250" fill="#0B0E14"\s*/>')
ARTWORK_START = "<!-- Lens"  # everything from here on is the lens, check and handle
NOTE = "<!-- Generated from {} by scripts/generate_logos.py. Do not edit. -->\n"

TILE = "loupebox-icon.svg"  # rounded tile: favicon and PWA "any" icons
MASKABLE = "loupebox-icon-maskable.svg"  # full-bleed with a safe zone, for maskable icons

# The README wordmarks are 800x250 with the dark one on an opaque background. The app wants them transparent
# and cropped to the artwork (measured: x 88-718, y 88-174, plus room for the neon glow).
WORDMARK_BACKGROUND = '  <rect width="800" height="250" fill="#0B0E14" />\n'
WORDMARK_VIEWBOX = ('viewBox="0 0 800 250"', 'viewBox="66 66 674 130"')

# (output file, source, size in px)
PNGS = [
    ("icon-192.png", TILE, 192),  # PWA manifest, purpose "any"
    ("icon-512.png", TILE, 512),  # PWA manifest, purpose "any"
    ("icon-maskable-512.png", MASKABLE, 512),  # PWA manifest, purpose "maskable"
    # iOS rounds the corners itself and fills transparency with black, so it gets the square artwork.
    ("apple-touch-icon.png", "brand/loupebox-icon-neon-dark.svg", 180),
    # Emails: the admin UI serves this at PUBLIC_URL. 96px shows crisply at 48px on retina screens.
    ("email-logo.png", TILE, 96),
]


def derive(art: str) -> dict[str, str]:
    """The tile and maskable SVGs, derived from the artwork by text edits that fail loudly if it changes."""
    if not BACKGROUND.search(art) or ARTWORK_START not in art:
        raise SystemExit(f"{ART.name} no longer has the expected background or artwork markers")
    head, art_body = art.split(ARTWORK_START, 1)
    art_body = ARTWORK_START + art_body.removesuffix("</svg>\n").removesuffix("</svg>")
    tile = BACKGROUND.sub(lambda m: m.group().replace("<rect ", '<rect rx="56" '), art)
    # The maskable safe zone is a central circle of 80% of the icon, so shrink the artwork inside it.
    shrink = f'<g transform="translate(125 125) scale(.8) translate(-125 -125)">\n{art_body}</g>\n</svg>\n'
    return {TILE: tile, MASKABLE: head + shrink}


def derive_wordmarks() -> dict[str, str]:
    """Transparent, cropped app wordmarks (brand/loupebox-wordmark-app-{light,dark}.svg), keyed by output name."""
    out = {}
    for variant in ("light", "dark"):
        art = (PUBLIC / "brand" / f"loupebox-wordmark-neon-{variant}.svg").read_text()
        if WORDMARK_VIEWBOX[0] not in art:
            raise SystemExit(f"loupebox-wordmark-neon-{variant}.svg no longer has the expected viewBox")
        out[f"brand/loupebox-wordmark-app-{variant}.svg"] = art.replace(WORDMARK_BACKGROUND, "").replace(*WORDMARK_VIEWBOX)
    return out


def main() -> int:
    if not shutil.which("rsvg-convert"):
        print("rsvg-convert not found. Install librsvg (brew install librsvg / apt install librsvg2-bin).", file=sys.stderr)
        return 1
    generated = [(derive(ART.read_text()), f"brand/{ART.name}"), (derive_wordmarks(), "the brand wordmarks")]
    for svgs, source in generated:
        for name, svg in svgs.items():
            (PUBLIC / name).write_text(svg.replace("\n", "\n" + NOTE.format(source), 1))  # the note goes under the <svg> line
            print(f"{name:24} generated")
    for name, source, size in PNGS:
        subprocess.run(
            ["rsvg-convert", "-w", str(size), "-h", str(size), str(PUBLIC / source), "-o", str(PUBLIC / name)], check=True
        )
        print(f"{name:24} {size}x{size}  from {source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
