"""Cut a customer's answer out of the thread their mail client quoted under it."""

import re

# "On Tue, Nov 3, 2026 at 9:14 AM Name <a@b.c> wrote:" (which clients wrap onto two lines), "---- Original
# Message ----", Outlook's From/Sent block, and the "-- " signature separator. Everything after is dropped.
_ORIGINAL = re.compile(r"^-{2,}\s*(original|forwarded) message\s*-{2,}$|^_{5,}$", re.IGNORECASE)
_OUTLOOK = re.compile(r"^(sent|date|to|subject):", re.IGNORECASE)


def _starts_quote(lines: list[str], i: int) -> bool:
    line = lines[i].strip()
    if line == "--" or _ORIGINAL.match(line):
        return True
    following = lines[i + 1].strip() if i + 1 < len(lines) else ""
    if line.lower().startswith("on ") and "wrote:" in f"{line} {following}":
        return True
    return line.lower().startswith("from:") and any(_OUTLOOK.match(x.strip()) for x in lines[i + 1 : i + 4])


def strip_quoted(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cut = next((i for i in range(len(lines)) if _starts_quote(lines, i)), len(lines))
    kept = lines[:cut]
    while kept and (not kept[-1].strip() or kept[-1].lstrip().startswith(">")):
        kept.pop()  # a quote block with nothing after it; quoted lines between the answer's own are kept
    return "\n".join(kept).strip()
