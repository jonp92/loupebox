"""Build the brand SVGs in web/public/brand from the sources in web/brand, with all text as paths.

    python -m scripts.outline_brand

The sources keep live <text> so they stay editable. The output has no font dependency, so it renders
the same everywhere (browsers, <img>, rsvg-convert). Edit web/brand/*.svg, run this, commit both.

Needs fonttools + uharfbuzz (pip install fonttools uharfbuzz), fontconfig's `fc-match` and the
Montserrat weights the sources use, installed as system fonts.
"""

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "brand"
OUT = ROOT / "web" / "public" / "brand"
SVG_NS = "http://www.w3.org/2000/svg"
FAMILY = "Montserrat"
STYLES = {"500": "Medium", "600": "SemiBold", "700": "Bold", "800": "ExtraBold"}  # CSS weight -> font style
FONT_ATTRS = ("font-family", "font-weight", "font-size", "letter-spacing")


@cache
def font(weight: str):
    import uharfbuzz as hb
    from fontTools.ttLib import TTFont

    style = STYLES[weight]
    path = subprocess.run(
        ["fc-match", "-f", "%{file}", f"{FAMILY}:style={style}"], capture_output=True, text=True, check=True
    ).stdout
    tt = TTFont(path)
    name = tt["name"].getDebugName(4)  # full font name, e.g. "Montserrat ExtraBold"
    if name != f"{FAMILY} {style}":
        sys.exit(f"{FAMILY} {style} is not installed (fc-match gave {name}, {path})")
    return tt, hb.Font(hb.Face(hb.Blob.from_file_path(path)))


def outline(text: str, weight: str, size: float, spacing: float, x: float, y: float) -> tuple[str, float]:
    """Shape `text` (kerning included) and return its outline as path data, plus the pen x after it."""
    import uharfbuzz as hb
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen

    tt, hbfont = font(weight)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hbfont, buf)
    glyphs, order = tt.getGlyphSet(), tt.getGlyphOrder()
    scale = size / tt["head"].unitsPerEm
    pen = SVGPathPen(glyphs, ntos=lambda n: f"{n:.2f}".rstrip("0").rstrip("."))
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        gx, gy = x + pos.x_offset * scale, y - pos.y_offset * scale
        glyphs[order[info.codepoint]].draw(TransformPen(pen, (scale, 0, 0, -scale, gx, gy)))
        x += pos.x_advance * scale + spacing  # CSS letter-spacing follows every glyph, the last one too
    return pen.getCommands(), x


def text_to_paths(el: ET.Element, inherited: dict) -> list[ET.Element]:
    """Replace a <text> (and its <tspan>s) with one <path> per run, keeping its position and flow."""
    attrs = {**inherited, **el.attrib}
    size = float(attrs["font-size"])
    spacing = attrs.get("letter-spacing", "0")
    spacing = float(spacing[:-2]) * size if spacing.endswith("em") else float(spacing)
    runs = [(el.text, attrs["font-weight"])]
    for span in el.findall(f"{{{SVG_NS}}}tspan"):
        runs += [
            (span.text, span.get("font-weight", attrs["font-weight"])),
            (span.tail, attrs["font-weight"]),
        ]
    runs = [(t, w) for t, w in runs if t and t.strip()]

    def lay_out(x: float) -> tuple[list[str], float]:
        ds = []
        for t, w in runs:
            d, x = outline(t, w, size, spacing, x, float(attrs["y"]))
            ds.append(d)
        return ds, x

    x = float(attrs["x"])
    if attrs.get("text-anchor") == "end":
        x -= lay_out(0)[1]
    return [ET.Element(f"{{{SVG_NS}}}path", d=d) for d in lay_out(x)[0]]


def outline_tree(parent: ET.Element, inherited: dict) -> None:
    for i, child in enumerate(list(parent)):
        if child.tag == f"{{{SVG_NS}}}text":
            paths = text_to_paths(child, inherited)
            paths[-1].tail = child.tail
            parent[i : i + 1] = paths
            continue
        outline_tree(child, {**inherited, **{k: v for k, v in child.attrib.items() if k in FONT_ATTRS}})
        for k in FONT_ATTRS:
            child.attrib.pop(k, None)


def main() -> int:
    try:
        import fontTools  # noqa: F401
        import uharfbuzz  # noqa: F401
    except ImportError:
        print("Needs fonttools and uharfbuzz: pip install fonttools uharfbuzz", file=sys.stderr)
        return 1
    if not shutil.which("fc-match"):
        print(
            "fc-match not found. Install fontconfig (brew install fontconfig / apt install fontconfig).",
            file=sys.stderr,
        )
        return 1
    ET.register_namespace("", SVG_NS)
    OUT.mkdir(exist_ok=True)
    for src in sorted(SRC.glob("*.svg")):
        root = ET.parse(src, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))).getroot()
        outline_tree(root, {})
        note = ET.Comment(f" Generated from web/brand/{src.name} by scripts/outline_brand.py. Do not edit. ")
        note.tail, root.text = root.text, "\n  "
        root.insert(0, note)
        ET.ElementTree(root).write(OUT / src.name, encoding="unicode")
        print(f"{src.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
