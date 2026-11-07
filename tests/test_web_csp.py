"""The admin app's Content-Security-Policy is written by the web container's startup script. These run
the real script, because a policy that is too tight breaks the page in production and nothing else
would notice."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "web" / "docker" / "40-config.sh"
API = "https://feedback.example.com"


def run(tmp_path, api_url=API):
    return subprocess.run(
        ["sh", str(SCRIPT)],
        env={"API_URL": api_url, "CONFIG_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


def policy(tmp_path) -> dict[str, list[str]]:
    header = (tmp_path / "csp.conf").read_text()
    value = header.split('Content-Security-Policy "', 1)[1].split('" always', 1)[0]
    return {d.split()[0]: d.split()[1:] for d in (part.strip() for part in value.split(";")) if d}


def test_pictures_fetched_with_the_login_token_may_be_shown(tmp_path):
    assert run(tmp_path).returncode == 0
    # blob: is what the feedback gallery uses; the API origin is for avatars.
    assert policy(tmp_path)["img-src"] == ["'self'", "blob:", API]


def test_self_hosted_fonts_are_allowed_from_this_origin_only(tmp_path):
    run(tmp_path)
    assert policy(tmp_path)["font-src"] == ["'self'"]


def test_everything_else_stays_closed(tmp_path):
    run(tmp_path)
    p = policy(tmp_path)
    assert p["default-src"] == ["'none'"]
    assert p["script-src"] == ["'self'"] and p["style-src"] == ["'self'"]  # no inline code, no other hosts
    assert p["connect-src"] == ["'self'", API]
    assert p["frame-ancestors"] == ["'none'"] and p["object-src"] == ["'none'"]
    assert not any(
        v in ("*", "data:", "'unsafe-inline'", "'unsafe-eval'") for values in p.values() for v in values
    )


def test_the_runtime_config_carries_the_api_origin(tmp_path):
    run(tmp_path, API + "/")
    assert (tmp_path / "config.js").read_text() == f'window.__CONFIG__ = {{"API_URL": "{API}"}};\n'


@pytest.mark.parametrize(
    "bad", ["javascript:alert(1)", "https://x.example/path", 'https://a.example"; evil', "ftp://x"]
)
def test_an_api_url_that_is_not_a_bare_origin_is_refused(tmp_path, bad):
    result = run(tmp_path, bad)
    assert result.returncode != 0 and not (tmp_path / "csp.conf").exists()
