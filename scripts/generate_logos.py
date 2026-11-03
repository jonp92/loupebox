"""Render every PNG logo from the SVG sources in web/public.

    python -m scripts.generate_logos

Needs `rsvg-convert` (macOS: brew install librsvg; Debian/Ubuntu: apt install librsvg2-bin).
Edit web/public/loupebox-icon.svg or loupebox-icon-maskable.svg, run this, commit the PNGs.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "web" / "public"
ICON = "loupebox-icon.svg"  # rounded tile, for "any" icons
MASKABLE = "loupebox-icon-maskable.svg"  # full-bleed with a safe zone, for maskable icons

# (output file, source svg, size in px, square corners)
TARGETS = [
    ("icon-192.png", ICON, 192, False),  # PWA manifest, purpose "any"
    ("icon-512.png", ICON, 512, False),  # PWA manifest, purpose "any"
    ("icon-maskable-512.png", MASKABLE, 512, False),  # PWA manifest, purpose "maskable"
    # iOS rounds the corners itself and fills transparency with black, so it needs a square tile.
    ("apple-touch-icon.png", ICON, 180, True),
    # Emails: the admin UI serves this at PUBLIC_URL. 96px shows crisply at 48px on retina screens.
    ("email-logo.png", ICON, 96, False),
]


def render(svg: Path, out: Path, size: int, square: bool) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = svg
        if square:
            source = Path(tmp) / svg.name
            source.write_text(svg.read_text().replace(' rx="15"', ""))  # the only rounded shape is the tile
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), str(source), "-o", str(out)], check=True)


def main() -> int:
    if not shutil.which("rsvg-convert"):
        print("rsvg-convert not found. Install librsvg (brew install librsvg / apt install librsvg2-bin).", file=sys.stderr)
        return 1
    for name, svg, size, square in TARGETS:
        render(PUBLIC / svg, PUBLIC / name, size, square)
        print(f"{name:24} {size}x{size}  from {svg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
