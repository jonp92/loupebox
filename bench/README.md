# Benchmarks

Load tests for Loupebox. Nothing here ships in the Docker image. Results go in the docs, with the hardware
they were measured on.

Everything runs against a **throwaway** Postgres called `bench`. The seeder refuses any other database.

## Set up (any machine with Docker, Python 3.12+ and this repo)

```bash
pip install -r requirements.txt psycopg   # or use the repo's .venv
export BENCH_CPUS=4 BENCH_MEM=8g          # match the box under test; record these with the results
docker compose -f bench/docker-compose.yml up -d
DATABASE_URL=postgresql+psycopg://bench:bench@127.0.0.1:55433/bench alembic upgrade head
DATABASE_URL=postgresql+psycopg://bench:bench@127.0.0.1:55433/bench python -m bench.seed --rows 1000000 --sites 50
```

The seed is deterministic (`--seed`). It writes `bench/out/sites.json` with the admin login and each
site's id, public key and allowed origin. Start over with `docker compose -f bench/docker-compose.yml down -v`.

## Run the API

```bash
. bench/env.sh                                    # database URL, no .env, public rate limits lifted
uvicorn app.main:app --port 18000 --workers 1
```

`BENCH_DEFAULT_LIMITS=1 . bench/env.sh` keeps the default rate limits. `BENCH_REDIS_URL` turns on the shared
limiter for the multi-replica runs.

## What the data looks like

* 1 superadmin, 50 sites, traffic skewed so site 1 holds about 22% of the rows, site 2 about 11%, and so on.
* Spread evenly over the last 365 days. Status: 50% new, 30% read, 15% archived, 5% spam.
* 30% of rows have 1 to 3 of 20 tags; 40% have an email address.
* Search terms with known frequency: `checkout` (about 5% of rows), `invoice` (0.5%), `zyxwvu` (0.01%).
