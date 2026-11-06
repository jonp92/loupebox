"""Drive the admin endpoints that read feedback, for a site with many rows and one with few.

    python -m bench.queries [http://127.0.0.1:18000]

Run it against a database started with docker-compose.explain.yml, then read the plans from
`docker compose logs db`. Prints one line per request.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18000") + "/v1/api"
DATA = json.loads((Path(__file__).parent / "out" / "sites.json").read_text())

FEEDBACK = {
    "list": "",
    "list page 400": "?offset=10000",
    "status=read": "?status=read",
    "status=spam": "?status=spam",
    "issue_type=bug": "?issue_type=bug",
    "rating=5": "?rating=5",
    "has_email": "?has_email=true",
    "dates, 30 days": "?created_from=2026-10-01&created_to=2026-10-31",
    "assignee=none": "?assignee=none",
    "tag": "?tag=tag03",
    "search common": "?q=checkout",
    "search rare": "?q=zyxwvu",
    "search + status": "?q=checkout&status=read",
}
OTHER = ["/counts", "/issue-types", "/tags", "/assignees"]


def get(path: str, headers: dict) -> None:
    req = urllib.request.Request(BASE + path, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            status = res.status
    except urllib.error.HTTPError as e:
        status = e.code
    print(f"{status} {path[:90]}")


login = urllib.request.Request(
    BASE + "/auth/login", json.dumps(DATA["login"]).encode(), {"content-type": "application/json"}
)
auth = {"authorization": "Bearer " + json.load(urllib.request.urlopen(login))["access_token"]}
for label, site in (("big", DATA["sites"][0]), ("small", DATA["sites"][-1])):
    print(f"-- {label} site")
    for query in FEEDBACK.values():
        get(f"/sites/{site['id']}/feedback{query}", auth)
    for path in OTHER:
        get(f"/sites/{site['id']}/feedback{path}", auth)
    get(f"/sites/{site['id']}/stats", auth)
print("-- instance")
get("/dashboard", auth)
get("/sites", auth)
