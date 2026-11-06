"""Check a seeded benchmark API end to end: login, admin reads, search, stats and public ingest.

    python -m bench.smoke [http://127.0.0.1:18000]

Prints one line per request with its time. Exits non-zero if any request fails.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18000") + "/v1/api"
DATA = json.loads((Path(__file__).parent / "out" / "sites.json").read_text())
failed = False


def call(label: str, path: str, body: dict | None = None, headers: dict | None = None) -> bytes:
    global failed
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json", **(headers or {})},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req) as res:
            status, out = res.status, res.read()
    except urllib.error.HTTPError as e:
        status, out = e.code, e.read()
    ms = (time.perf_counter() - start) * 1000
    failed |= status >= 400
    print(f"{label:<22} {status} {ms:7.1f} ms {len(out):>8} bytes")
    return out


token = json.loads(call("login", "/auth/login", DATA["login"]))["access_token"]
auth = {"authorization": f"Bearer {token}"}
site = DATA["sites"][0]
sid = site["id"]
call("sites", "/sites", headers=auth)
call("list", f"/sites/{sid}/feedback?limit=25", headers=auth)
call("list filtered", f"/sites/{sid}/feedback?status=read&limit=25", headers=auth)
call("search common", f"/sites/{sid}/feedback?q=checkout", headers=auth)
call("search rare", f"/sites/{sid}/feedback?q=zyxwvu", headers=auth)
call("counts", f"/sites/{sid}/feedback/counts", headers=auth)
call("stats", f"/sites/{sid}/stats", headers=auth)
call(
    "ingest",
    "/feedback",
    {"message": "bench smoke test"},
    {"x-api-key": site["key"], "origin": site["origin"]},
)
sys.exit(1 if failed else 0)
