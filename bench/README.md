# Benchmarks

Load tests for Loupebox. Nothing here ships in the Docker image. Results go in the docs, with the hardware
they were measured on.

Everything runs against a **throwaway** Postgres called `bench`. The seeder refuses any other database.

## Set up the system under test (any machine with Docker and this repo)

Only Docker is needed. Postgres and the API run from the repo's own image, so the numbers describe what users
deploy.

```bash
export BENCH_CPUS=4 BENCH_MEM=4g          # caps Postgres only; the API is uncapped. Record both.
C="docker compose -f bench/docker-compose.yml"
R="$C run --rm --no-deps -T --user $(id -u):$(id -g) -v $PWD/bench:/srv/bench"
mkdir -p bench/out
$C up -d --build
$R api alembic upgrade head
$R api python -m bench.seed --rows 1000000 --sites 50
$C restart api && $R api python -m bench.smoke http://api:8000
```

The seed is deterministic (`--seed`) and writes `bench/out/sites.json` with the admin login and each site's id,
public key and allowed origin. Start over with `$C down -v`. The API listens on port 18000 of the machine
(`BENCH_API_PORT`, `BENCH_API_BIND`). Its settings are in `bench/bench.env`, which lifts the rate limits (one
load generator is one IP); delete the `*_LIMIT` lines to measure with the defaults.

Without Docker for the API, `. bench/env.sh` loads the same settings for a Python checkout
(`uvicorn app.main:app --port 18000`).

## What the data looks like

* 1 superadmin, 50 sites, traffic skewed so site 1 holds about 22% of the rows, site 2 about 11%, and so on.
* Spread evenly over the last 365 days. Status: 50% new, 30% read, 15% archived, 5% spam.
* 30% of rows have 1 to 3 of 20 tags; 40% have an email address.
* Search terms with known frequency: `checkout` (about 5% of rows), `invoice` (0.5%), `zyxwvu` (0.01%).

## Load tests (k6)

On the machine that generates the load, copy `bench/` (including `bench/out/sites.json` from the seeder).
[k6](https://grafana.com/docs/k6/latest/set-up/install-k6/) is used if installed, otherwise the `grafana/k6`
image. With the API running and the data seeded:

```bash
bench/run.sh list                        # one scenario, quick defaults
bench/run.sh ingest_many -e BASE_URL=http://10.0.0.5:18000 -e START=50 -e STEP=50 -e STEPS=8
```

Each run prints a summary with one line per endpoint (p50 to p99) and saves it to `bench/out/results/`.
Scenarios are in `bench/k6/loupebox.js`:

| Scenario | What it does |
|---|---|
| `ingest_many` | Public `POST /feedback` spread over all 50 sites |
| `ingest_hot` | The same, all into the busiest site (it takes a row lock per site) |
| `list` | Opening a feedback page: list, counts, issue types and tags |
| `filters` | The list with a random filter |
| `search` | The list with a search term (`checkout`, `invoice` or `zyxwvu`) |
| `dashboard` | `GET /dashboard` as the superadmin (the heaviest case: it sees every site) |
| `stats` | `GET /sites/{id}/stats` |
| `mixed` | Steady ingest while people browse (`MIX_INGEST`, `MIX_PAGES`, `MIX_SEARCH`, `MIX_DASHBOARD` per second, `DURATION` seconds) |

The single-endpoint scenarios raise the request rate in steps: `START` per second, plus `STEP` every
`STEP_SECONDS`, `STEPS` times. Watch where the p95 climbs or errors start; that step is the limit. The
generator needs headroom of its own: if k6 reports dropped iterations or uses a whole CPU, add `VUS` / `MAX_VUS`
or move it to another machine. For published numbers run it on a separate machine from the API and database.
