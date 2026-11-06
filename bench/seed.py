"""Fill a THROWAWAY Postgres with made-up feedback for benchmarks.

    docker compose -f bench/docker-compose.yml up -d
    DATABASE_URL=postgresql+psycopg://bench:bench@127.0.0.1:55433/bench alembic upgrade head
    DATABASE_URL=... python -m bench.seed --rows 1000000 --sites 50

Refuses anything but a database called "bench" on localhost, and refuses a database that already has
sites (reset with `docker compose -f bench/docker-compose.yml down -v`). Writes bench/out/sites.json
with the ids and public keys the load scripts need.
"""

import argparse
import hashlib
import json
import os
import random
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import psycopg

from app.core.security import hash_password

OUT = Path(__file__).parent / "out"
PASSWORD = "bench-password-123"
EMAIL = "bench@example.com"
BATCH = 50_000

WORDS = (  # noqa: SIM905 (one string reads better than a list of 100 words)
    "the a to and it is was on for with this that app page button load slow fast login sign password "
    "export import search filter list detail view save edit delete update mobile phone tablet desktop "
    "browser dark light theme color font size small large menu link form field error message email "
    "notification setting account profile team member role billing plan price feature request bug fix "
    "crash freeze scroll click tap swipe image upload download report chart table row column sort "
    "dashboard wish love hate great good bad confusing missing broken works never always sometimes "
    "after before when while because maybe please thanks hello"
).split()
# Search terms with known frequency, for the search scenario: ~5%, ~0.5%, ~0.01% of rows.
NEEDLES = [("checkout", 0.05), ("invoice", 0.005), ("zyxwvu", 0.0001)]
ISSUE_TYPES = ["bug", "idea", "question", "praise"]
TAGS = [f"tag{i:02d}" for i in range(20)]
STATUS = ["new"] * 50 + ["read"] * 30 + ["archived"] * 15 + ["spam"] * 5
AGENTS = ["Mozilla/5.0 (Macintosh)", "Mozilla/5.0 (iPhone)", "Mozilla/5.0 (Windows NT 10.0)", "curl/8"]


def connect_info(url: str) -> str:
    """Return the psycopg DSN after checking this is the throwaway database."""
    u = urlparse(url.replace("+psycopg", ""))
    if u.hostname not in ("localhost", "127.0.0.1") or u.path != "/bench":
        sys.exit(f"Refusing to seed {u.hostname}{u.path}: only a local database named bench.")
    return url.replace("+psycopg", "")


def message(rng: random.Random) -> str:
    words = rng.choices(WORDS, k=rng.randint(8, 60))
    for needle, share in NEEDLES:
        if rng.random() < share:
            words.insert(rng.randrange(len(words)), needle)
    return " ".join(words)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1_000_000)
    ap.add_argument("--sites", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    dsn = connect_info(os.environ["DATABASE_URL"])
    rng = random.Random(args.seed)
    now = datetime.now(UTC)

    with psycopg.connect(dsn) as conn:
        if conn.execute("SELECT count(*) FROM sites").fetchone()[0]:
            sys.exit("The database already has sites. Reset it with `docker compose down -v` first.")
        conn.execute(
            "INSERT INTO users (id, email, first_name, last_name, password_hash, is_superadmin, is_active, "
            "created_at) VALUES (%s, %s, 'Bench', 'Admin', %s, true, true, %s)",
            (uuid.uuid4(), EMAIL, hash_password(PASSWORD), now),
        )
        # Traffic is skewed: site 1 gets 1/1 of the weight, site 2 gets 1/2, and so on.
        weights = [1 / (i + 1) for i in range(args.sites)]
        sites = [
            {
                "id": str(uuid.uuid4()),
                "name": f"Bench site {i + 1:03d}",
                "key": f"bench_{i + 1:03d}_{secrets.token_hex(8)}",
                "origin": f"https://site{i + 1}.example.com",
            }
            for i in range(args.sites)
        ]
        for s in sites:
            conn.execute(
                "INSERT INTO sites (id, name, public_key, allowed_origins, is_active, daily_limit, "
                "challenge_mode, challenge_config, created_at) "
                "VALUES (%s, %s, %s, %s::json, true, 10000000, 'off', '{}', %s)",
                (s["id"], s["name"], s["key"], json.dumps([s["origin"]]), now),
            )
        conn.commit()

        done = 0
        while done < args.rows:
            n = min(BATCH, args.rows - done)
            fb, tg = [], []
            for _ in range(n):
                fid = uuid.uuid4()
                site = rng.choices(sites, weights)[0]["id"]
                msg = message(rng)
                email = f"user{rng.randrange(100_000)}@example.com" if rng.random() < 0.4 else None
                meta = json.dumps({"browser": "bench", "issue_type": rng.choice(ISSUE_TYPES)})
                created = now - timedelta(seconds=rng.randrange(365 * 86400))
                digest = hashlib.sha256(f"{site}\n{msg.lower()}\n{email or ''}".encode()).hexdigest()
                fb.append(
                    (
                        fid, site, msg, rng.choice([None, 1, 2, 3, 4, 5]),
                        f"Visitor {rng.randrange(1000)}" if email else None, email,
                        f"https://site.example.com/p/{rng.randrange(500)}", meta,
                        rng.choice(STATUS), digest, secrets.token_hex(16), rng.choice(AGENTS), created,
                    )
                )  # fmt: skip
                if rng.random() < 0.3:
                    tg.extend((fid, t) for t in rng.sample(TAGS, rng.randint(1, 3)))
            with conn.cursor() as cur:
                with cur.copy(
                    "COPY feedback (id, site_id, message, rating, name, email, page_url, meta, status, "
                    "content_hash, ip_hash, user_agent, created_at) FROM STDIN"
                ) as copy:
                    for row in fb:
                        copy.write_row(row)
                with cur.copy("COPY feedback_tags (feedback_id, tag) FROM STDIN") as copy:
                    for row in tg:
                        copy.write_row(row)
            conn.commit()
            done += n
            print(f"{done:>9,} / {args.rows:,} rows", flush=True)

        conn.autocommit = True
        for table in ("sites", "feedback", "feedback_tags"):
            conn.execute(f"ANALYZE {table}")
        size = conn.execute("SELECT pg_size_pretty(pg_total_relation_size('feedback'))").fetchone()[0]

    OUT.mkdir(exist_ok=True)
    (OUT / "sites.json").write_text(
        json.dumps({"login": {"email": EMAIL, "password": PASSWORD}, "sites": sites}, indent=1)
    )
    print(f"Done. feedback table with indexes: {size}. Site list: {OUT / 'sites.json'}")


if __name__ == "__main__":
    main()
