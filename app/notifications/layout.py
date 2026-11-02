"""HTML shell for outgoing emails, styled after the admin UI (web/src/styles.css).

Email clients ignore most CSS, so the layout is a table with inline styles. A small <style> block
adds dark mode for the clients that honour it (Apple Mail, iOS); the rest keep the light theme.
Callers pass already-escaped HTML: every user-supplied string must go through `escape()` first.
"""

from html import escape

from app.core.config import settings

ACCENT = "#5b5bd6"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

_DARK = """
@media (prefers-color-scheme: dark) {
  .bg { background: #0f1117 !important; }
  .card { background: #181b25 !important; border-color: #2b3040 !important; }
  .text { color: #e8eaf2 !important; }
  .muted { color: #98a0b8 !important; }
  .quote { background: #20242f !important; border-left-color: #8c8cf5 !important; }
  .lnk { color: #8c8cf5 !important; }
  .rule { border-color: #2b3040 !important; }
  .btn { background: #8c8cf5 !important; color: #10111a !important; }
}
"""


def facts_table(rows: list[tuple[str, str]]) -> str:
    """Label/value rows. Values are already-escaped HTML."""
    cells = "".join(
        f'<tr><td class="muted" style="padding:2px 12px 2px 0;color:#6a6f85;font-size:13px;white-space:nowrap" valign="top">{escape(k)}</td>'
        f'<td class="text" style="padding:2px 0;color:#171923;font-size:14px" valign="top">{v}</td></tr>'
        for k, v in rows
    )
    return f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:16px 0 0">{cells}</table>'


def quote(html: str) -> str:
    """The feedback text, set off like the accented card edge in the UI."""
    return (
        f'<div class="quote text" style="margin:16px 0 0;padding:14px 16px;background:#f0f1f6;'
        f'border-left:4px solid {ACCENT};border-radius:6px;color:#171923;font-size:15px;line-height:1.5">{html}</div>'
    )


def _brand() -> str:
    """The logo image when PUBLIC_URL says where it is served from, else a plain accent dot."""
    base = settings.public_url.rstrip("/")
    mark = (
        f'<img src="{escape(base, quote=True)}/email-logo.png" width="24" height="24" alt="" '
        'style="display:inline-block;vertical-align:middle;border:0;border-radius:6px;margin-right:8px">'
        if base
        else f'<span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:{ACCENT};margin-right:8px"></span>'
    )
    return f'{mark}<span style="vertical-align:middle">Ganymede</span>'


def render(*, heading: str, preheader: str, body: str, link: str | None, site: str) -> str:
    """`heading`, `preheader`, `site` are plain text (escaped here); `body` is HTML."""
    button = (
        f'<p style="margin:24px 0 0"><a class="btn" href="{escape(link, quote=True)}" '
        f'style="display:inline-block;padding:10px 18px;background:{ACCENT};color:#ffffff;'
        'text-decoration:none;font-weight:600;font-size:14px;border-radius:8px">Open in Ganymede</a></p>'
        if link
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{escape(heading)}</title>
<style>{_DARK}</style>
</head>
<body class="bg" style="margin:0;padding:0;background:#f0f1f6">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{escape(preheader)}</div>
<table role="presentation" class="bg" width="100%" cellpadding="0" cellspacing="0" style="background:#f0f1f6">
<tr><td align="center" style="padding:24px 12px">
  <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="width:100%;max-width:560px">
    <tr><td style="padding:0 4px 14px;font-family:{FONT};font-size:15px;font-weight:700;color:{ACCENT}">
      {_brand()}
    </td></tr>
    <tr><td class="card" style="background:#ffffff;border:1px solid #e1e3ec;border-radius:10px;padding:24px;font-family:{FONT}">
      <div class="muted" style="color:#6a6f85;font-size:13px">{escape(site)}</div>
      <h1 class="text" style="margin:4px 0 0;color:#171923;font-size:20px;line-height:1.3;letter-spacing:-0.01em">{escape(heading)}</h1>
      {body}
      {button}
    </td></tr>
    <tr><td class="muted" style="padding:14px 4px 0;font-family:{FONT};color:#6a6f85;font-size:12px;line-height:1.5">
      You get this because you are subscribed to notifications for this site.
    </td></tr>
  </table>
</td></tr>
</table>
</body></html>"""
