"""The icon, the wordmark's lens and the React components all come from scripts/brand_art.py."""

import re

import pytest

from scripts import brand_art

pytestmark = pytest.mark.skipif(
    not brand_art.FONTS.parent.exists(), reason="needs `npm ci` in web/ for the Hanken Grotesk files"
)


def test_committed_brand_files_are_current():
    # Fails after editing tokens.css or brand_art.py without running `python -m scripts.brand_art`.
    stale = [
        str(p.relative_to(brand_art.ROOT)) for p, text in brand_art.render().items() if p.read_text() != text
    ]
    assert not stale, f"run python -m scripts.brand_art and commit: {stale}"


def test_icon_and_wordmark_lens_are_the_same_drawing():
    ratios = []
    for name in ("icon", "wordmark"):
        svg = (brand_art.BRAND / f"loupebox-{name}-light.svg").read_text()
        r = float(re.search(r'<circle[^>]* r="([\d.]+)"', svg).group(1))
        widths = [float(w) for w in re.findall(r'stroke-width="([\d.]+)"', svg)]
        ratios.append([round(w / r, 2) for w in widths])
    assert ratios[0] == ratios[1]
