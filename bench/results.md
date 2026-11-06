# Benchmark results (2026-11-06)

The first full sweep with the scripts in this folder, and how the numbers changed as each problem it found was
fixed. **Each number is one run, so read them as measurements to compare against each other, not as final figures.**
The goal was to find what breaks first, and then to check each fix against the same scenarios.

## Setup

| | |
|---|---|
| System under test | One VM: 4 vCPU (generic QEMU CPU, KVM), 7.8 GB RAM, Ubuntu 26.04, Docker 29.9 |
| Postgres | 17, container capped at 4 CPUs and 4 GB, **default settings** (not tuned) |
| API | The repo's own image (Python 3.11), **one** Uvicorn worker, no Redis. Pool of 5 + 10 connections |
| Data | 1M feedback rows over 50 sites (site 1 holds about 22%); 1,126,365 by the end, because the ingest runs add rows |
| Load generator | A second VM on the same hypervisor, k6 in Docker, not capped. Round trip to the first VM 0.27 ms |
| Rate limits | Lifted (one generator is one IP), see `bench.env` |
| CPU steal on the system under test | 0% for every run |
| Shape | Each step lasts 20 s and ramps linearly to its target, so the average rate in a step is lower than its target. Requests time out after 10 s |

## How the numbers changed

"Sustained" is the highest step reached before p95 went over 1 s or more than 1% of requests failed; for the page
load it is the slowest of its four requests. Rates are per second, and one page load is four requests. A "not
reached" means the range I tested ended first, so the real ceiling is higher.

| Scenario | First baseline | After the pool fix ([#88](https://github.com/jonp92/loupebox/pull/88)) | After the list index ([#90](https://github.com/jonp92/loupebox/pull/90)) | After menus and dashboard ([#92](https://github.com/jonp92/loupebox/pull/92)) |
|---|---|---|---|---|
| `ingest_many` (public POST, requests/s) | 250. At 300: p95 10 s, 31% failed, API stuck | 250. At 300: p95 2 s, 1% turned away, API answers | 250. Same | not rerun |
| `list` (page loads/s) | 10 (p95 700 ms). At 15: 36% failed, API stuck | 10 (p95 645 ms). At 15: p95 2.6 s | 10 (p95 260 ms). At 15: p95 1.8 s, 0% failed | **40, not reached** (p95 38 ms, 0% failed) |
| `filters` (requests/s) | 40 (p95 540 ms). At 50: 27% failed | 30 (p95 226 ms). At 40: p95 1.0 s | **80, not reached** (p95 373 ms) | not rerun |
| `search` (searches/s) | 6 (p95 555 ms). At 8: p95 1.0 s | 10 (p95 947 ms). At 12: p95 3.4 s | 10 (p95 740 ms). At 12: p95 1.0 s | not rerun |
| `dashboard` (loads/s) | 5 (p95 790 ms). At 6: p95 4.3 s | 4 (p95 706 ms). At 5: p95 2.6 s | 7 (p95 666 ms). At 8: p95 3.1 s | **8, not reached** (p95 311 ms) |
| `stats` (requests/s) | 150, not reached (p95 29 ms) | 150, not reached (p95 40 ms) | not rerun | not rerun |
| `mixed` (20 ingests, 5 page loads, 2 searches, 1 dashboard per second, 120 s) | 100% failed after the first 30 s, API stuck | 1.3% failed. Ingest p95 1.9 s, search 4.4 s, dashboard 5.6 s | not rerun | **0% failed.** Ingest p95 18 ms, list 19 ms, search 545 ms, dashboard 376 ms |

What the table says:

* **Ingest capacity did not change.** It is limited by one Python process and was about 250 requests per second in
  every run. The pool fix changed how it fails: past that rate requests wait up to 2 s and a few are turned away,
  instead of timing out and leaving the API stuck.
* **The big wins are on reads.** The page load went from breaking at about 12 per second to no limit found up to 40.
  The list request itself went from p50 81 ms to 8 ms, `filters` moved from breaking at 40 to 80 or more, and the
  dashboard for one user went from 523 ms to 248 ms.
* **Search barely moved** through these three fixes. It was the slowest read (about 210 ms at the median under
  `mixed`); the trigram index in [#94](https://github.com/jonp92/loupebox/pull/94) fixed it, see below.
* Small differences between the first three columns (for example `filters` at 40 against 30, or the dashboard at
  5 against 4) are within run-to-run noise.
* Only `list`, `dashboard` and `mixed` were rerun after the last change, so the `filters`, `search` and `ingest_many`
  cells in that column are blank. Rerun them before quoting a final figure.

## The first baseline in detail

"Clean" means p95 stayed low and nothing failed. The knee is where p95 starts to climb. Rates are requests per
second unless noted.

| Scenario | Clean up to | Knee | Breaks |
|---|---|---|---|
| `ingest_many` | about 175, p95 8 ms | about 225, p95 76 ms | about 275: p95 10 s, 31% failed |
| `ingest_hot` (all into one site) | about 130, p95 9 ms | about 150, p95 114 ms | not reached (range topped out at 160) |
| `list` (page loads/s) | 5, p95 about 200 ms | about 8, p95 about 700 ms | about 12 |
| `filters` | about 25, p95 214 ms | about 35, p95 540 ms | about 40: 27% failed |
| `search` | about 5, p95 555 ms | about 7, p95 1 s | about 12 to 14: 23% failed |
| `dashboard` | about 4, p50 560 ms, p95 635 ms | about 5, p95 790 ms | about 6: p95 4.3 s |
| `stats` | 150 and above, p95 29 ms | none seen | not reached |

Single requests were slow even at the quietest step: p50 about 80 ms for the list, 210 ms for a search, 525 ms for
the dashboard. `ingest_hot` was only measured in this first run; its range was too low to find where it breaks.

## What stopped the API, and what fixed it

After every scenario that overloaded it, the API stopped answering, even its health check, with no clients
connected. It recovered on its own once, after about 9.5 minutes. There were two causes, found with `py-spy` dumps
of the stuck process:

1. **A request keeps its database connection across thread hops.** When more requests are in flight than there are
   connections, the extra ones fill all 40 worker threads waiting for a connection, and the requests that hold the
   connections cannot get a thread to finish on. Nothing moves until the 30 s pool timeout.
2. **A database query ran on the event loop.** The CORS origin list reloads every 30 s from the database, and that
   ran on the loop itself. With the pool full, the whole server froze.

I tried the obvious fixes one at a time on the `mixed` scenario (each one run):

| Change | Failed | API after the load |
|---|---|---|
| None (defaults) | 74% | stuck |
| Bigger pool (40 connections) | 61% | stuck |
| Fewer threads (15) | 87% | stuck |
| Shorter pool wait (5 s) | 72% | stuck |
| Origin lookup off the event loop only | 62% | stuck for 5+ minutes |
| Limit on requests in flight only | 21% | stuck |
| **Both** (the fix in #88) | **1.3%** | **answered at once** |

The limit lets only as many requests run as the pool can serve; the rest wait up to 2 s, then get a `503`. CPU was
not the limit for ingest (the VM was mostly idle when it failed); the read scenarios used it fully (94% for `list`).

## Where the reads were slow, and the fixes

* Counts behind every list view, the filter menus and the dashboard each read the whole site
  ([plans.md](plans.md)). The 237,000-row site's list count took 56 ms.
* **#90:** the list stops counting at 10,000 and an index on `(site_id, status, created_at)` answers the status
  filter. The count went from 56 ms to about 1 ms.
* **#92:** the quick-tab counts stop at the same cap, the tag and issue-type menus are cached for 30 s, and the
  dashboard counts in one pass. I tested an index for the menus first; it did not help.
* **#94:** trigram indexes for search, see the next section.
* **Not fixed:** the dashboard's exact counts over the whole table (about 250 ms for a superadmin).

## Search with trigram indexes ([#94](https://github.com/jonp92/loupebox/pull/94))

Measured afterwards on the same VM and data (1.13M rows). The build is the same both times and only the indexes
differ: three GIN `pg_trgm` indexes on `message`, `email` and `name` (192 + 21 + 12 MB on a 548 MB table, built
in about 35 s), created with SQL and dropped again for the plain runs. Each number is one run.

A search request runs two queries, a count that stops at 10,001 and the page. Per query, warm, on the largest
site (237,000 rows). In this data `checkout` is in 15.6% of the rows, `invoice` 0.45% and `zyxwvu` 0.009%:

| Term | Count, plain | Count, indexed | Page, plain | Page, indexed |
|---|---|---|---|---|
| `checkout` (common) | 53 ms | 59 ms | 0.0 ms | 0.0 ms |
| `invoice` (medium) | 161 ms | 19 ms | 22 ms | 22 ms |
| `zyxwvu` (rare) | 151 ms | 0.2 ms | 149 ms | 0.2 ms |

A common word was already cheap, because the page stops after 25 matches and the count stops at its cap. The index
helps where the plain query had to read the whole site. On a small site (7,800 rows) the rare word went from
11.5 ms to 0.7 ms, but the common word's count got slower, 12 ms to 23 ms: a trigram index covers the whole
table, not one site, so a common word makes Postgres read a big bitmap for a small site.

The `search` scenario (95th percentile, one run each; "ramp to" is the rate a step ramps up to):

| Ramp to /s | 8 | 10 | 12 | 14 | 16 |
|---|---|---|---|---|---|
| Plain | 547 ms | 770 ms | 3.8 s | 5.2 s, 16% failed | 5.0 s, 30% failed |
| Indexed | 81 ms | 152 ms | 101 ms | 82 ms | 188 ms |

Indexed, the median stayed at 15 to 37 ms and nothing failed up to the top of the range, so the real ceiling is
higher; plain, the median went from 150 to 300 ms to 2.5 s at the top.

### Does the index slow ingest down?

`ingest_many` with one worker (the setup above) and with three (`--workers 3`, the other settings unchanged),
indexed and plain. The 95th percentile in ms; the three-worker runs were done twice, in the order indexed, plain,
indexed, plain, and the cells show both:

| Ramp to /s | 1 worker, plain | 1 worker, indexed | 3 workers, plain | 3 workers, indexed |
|---|---|---|---|---|
| 250 | 13 | 92 | 13, 9 | 10, 15 |
| 300 | 2,069 (3% failed) | 2,068 (3% failed) | 145, 11 | 13, 18 |
| 400 | 2,084 (14% failed) | 2,084 (14% failed) | 219, 51 | 55, 29 |
| 450 | 2,085 (14% failed) | 2,085 (14% failed) | 484, 153 | 579, 161 |
| 500 | 2,083 (13% failed) | 2,082 (13% failed) | 1,611, 1,391 | 1,399, 1,183 |

* **Three workers sustain a ramp to 450 requests per second against 250 for one**, with nothing failing, so the
  limit on ingest was the single Python process. In production more than one worker needs `REDIS_URL`; the
  benchmark lifts the rate limits instead.
* **The indexes show no consistent cost.** The runs overlap and the order of the pairs flips. The one gap, 92 ms
  against 13 ms at a ramp to 250 on one worker, did not appear on three workers (10 and 15 ms against 13 and 9 ms).
  With one run per cell a small cost cannot be ruled out.
* The VM has 4 vCPUs shared by the three workers and Postgres, so three workers is not the same as three times
  the capacity.

## To do before quoting numbers

* Repeat each scenario at least three times and keep the median.
* Rerun `ingest_hot`, `stats` and the last two columns' blanks, and extend the ranges for the cells marked "not
  reached", so each has a real ceiling.
* Find the threshold of `mixed` by running it at higher rates.
* Tune Postgres (the default `shared_buffers` is 128 MB) and see how much that changes the read scenarios.
* Try more than one Uvicorn worker on the other scenarios too (with Redis for the shared rate limits). Only
  `ingest_many` was tried, see the last section.
* The summaries in `bench/out/results/` contain the throwaway admin token, so do not publish them as they are.
