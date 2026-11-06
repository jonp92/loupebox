# Query plans at 1M rows (Phase 1)

Real plans from Postgres `auto_explain` while `bench/queries.py` drove the admin API. Data: 1M feedback rows,
50 sites; the "big" site holds about 22% of them (about 220k rows), the "small" one a few hundred. Postgres 17
capped at 2 CPUs and 4 GB on a shared 4 vCPU VM.

**Read these as pointers, not results.** Each query ran once, partly from a cold cache (many `read=` buffers),
with `auto_explain` timing every node, on a machine with other services. The plan shapes are reliable; the
millisecond figures are not. The load tests are what measure.

## What the plans show

Only two feedback indexes exist: `(site_id, created_at)` and `(site_id, content_hash)`, plus the foreign
key on `assignee_id`. Everything that filters on anything else falls through.

| Query (big site) | Plan | Time seen |
|---|---|---|
| Count behind every list view (`status != spam`, plus any filter) | Parallel Seq Scan of the **whole table** | 56 to 154 ms |
| Count with search (`q=`) | Bitmap scan of the site's rows, then `ILIKE` on message, email and name | 200 to 310 ms |
| List page with search | Gather Merge sort of every match, reading about 64k buffers | 350 ms |
| Dashboard: recent unread (all sites) | Hash join, Seq Scan of the whole table, top-N sort | 357 ms |
| Dashboard: unread per site, assigned count | Parallel Seq Scan, grouped | 99 to 115 ms |
| Tag list for the filter menu | Whole-table scan, joined to tags, grouped | 167 ms |
| Issue-type list (`meta->>'issue_type'`) | Whole-table scan, grouped | 112 ms |
| Date-range count (30 days) | Bitmap scan on `(site_id, created_at)` | 73 ms |
| Tag filter count | Tag index, then nested loop to feedback | 102 ms |
| Stats (14 day group-by) | Bitmap scan on `(site_id, created_at)` | 26 ms |
| List page, no search (including offset 10000) | Backward index scan, stops after 25 rows | under 80 ms |
| Small site, any of the above | Bitmap scan of its own rows | 10 to 35 ms |

## Reading it

1. **A count costs as much as the table, not the site.** For the big site the planner chose a Parallel Seq
   Scan over all 736 MB because 22% of the rows match. Every list view runs one, and the filter menu
   (`/counts`, `/tags`, `/issue-types`) adds more. Parallel workers also use every CPU, so this will hurt
   most when requests overlap.
2. **Search has no index.** `icontains` becomes `ILIKE '%q%'` on three columns. A rare term costs as much as
   a common one because both must read every row of the site.
3. **The dashboard scans the table five times** for anyone who can see many sites (a superadmin sees all).
   Someone with one small site pays far less.
4. **What is fine:** paging (even to offset 10000), the date range, stats and the small sites.
5. **Not covered yet:** ingest under load (it takes a row lock on the site), the worker, export, and
   anything concurrent.

## Candidates to try (hypotheses; each one gets a before and after)

* A narrower index so the counts can be answered from the index, for example `(site_id, status)`, or
  `(site_id, status, created_at)`. This makes them cheaper but still proportional to the site's size.
* Avoid exact totals for big sites: show "10,000+" past a cap, or keep per-status counters (there is already a
  `SiteStat` table for daily counters).
* Search: `pg_trgm` GIN indexes help rare terms a lot and common terms little. Shipped as migration `0017`.
* Issue types: an expression index on `(site_id, (meta->>'issue_type'))`. Tags: carry `site_id` on
  `feedback_tags` so the menu does not join to feedback.
* Dashboard: one grouped query instead of five, or cached per-site unread counts.

## How to reproduce

```bash
export BENCH_CPUS=2 BENCH_MEM=4g DATABASE_URL=postgresql+psycopg://bench:bench@127.0.0.1:55433/bench
C="docker compose -f bench/docker-compose.yml -f bench/docker-compose.explain.yml"
$C up -d && alembic upgrade head && python -m bench.seed --rows 1000000 --sites 50
. bench/env.sh && uvicorn app.main:app --port 18000 &
python -m bench.queries && $C logs db --no-log-prefix > bench/out/pg.log
```
