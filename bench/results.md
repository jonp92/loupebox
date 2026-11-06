# Baseline results (2026-11-06)

First full sweep with the scripts in this folder. **One run per scenario, so read them as a first
measurement, not a final number.** The goal was to find what breaks first.

## Setup

| | |
|---|---|
| System under test | One VM: 4 vCPU (generic QEMU CPU, KVM), 7.8 GB RAM, Ubuntu 26.04, Docker 29.9 |
| Postgres | 17, container capped at 4 CPUs and 4 GB, **default settings** (not tuned) |
| API | The repo's own image (Python 3.11), **one** Uvicorn worker, default database pool (5 + 10), no Redis |
| Data | 1M feedback rows over 50 sites (site 1 holds about 22%), 1,044,127 by the end (ingest runs add rows) |
| Load generator | A second VM on the same hypervisor, k6 in Docker, not capped. Round trip to the first VM 0.27 ms |
| Rate limits | Lifted (one generator is one IP), see `bench.env` |
| CPU steal on the system under test | 0% for the whole sweep |
| Shape | Each step lasts 20 s and ramps linearly to its target, so the average rate in a step is lower than its target. Requests time out after 10 s |

## What each scenario showed

"Clean" means p95 stayed low and nothing failed. The knee is where p95 starts to climb. Rates are requests per
second unless noted.

| Scenario | Clean up to | Knee | Breaks |
|---|---|---|---|
| `ingest_many` (public POST, all sites) | about 175, p95 8 ms | about 225, p95 76 ms | about 275: p95 10 s, 31% failed |
| `ingest_hot` (all into one site) | about 130, p95 9 ms | about 150, p95 114 ms | not reached (range topped out at 160) |
| `list` (page load = 4 requests) | 5 page loads/s, p95 about 200 ms | about 8 page loads/s, p95 about 700 ms | about 12 page loads/s |
| `filters` (one list request) | about 25, p95 214 ms | about 35, p95 540 ms | about 40: 27% failed |
| `search` | about 5, p95 555 ms | about 7, p95 1 s | about 12 to 14: 23% failed |
| `dashboard` (superadmin, all sites) | about 4, p50 560 ms, p95 635 ms | about 5, p95 790 ms | about 6: p95 4.3 s |
| `stats` | **150 and above**, p95 29 ms | none seen | not reached (range topped out at 150) |
| `mixed` (20 ingest, 5 page loads, 2 searches, 1 dashboard per second) | the first 30 s only, about 1% failed | | after 30 s: 100% failed for the rest of the 120 s |

Single requests are also slow at the quietest step: p50 about 80 ms per request on the list page, 210 ms for a
search, 525 ms for the dashboard.

## What stopped the API

* **After every scenario that overloaded it** (`ingest_many`, `list`, `filters`, `search`, `dashboard`, `mixed`) the
  API stopped answering, even its health check, with no clients connected. Once it recovered on its own after
  about 9.5 minutes. The other times it was restarted.
* During the first stall every one of the 40 worker threads was waiting in `resolve_site` for a database
  connection (`py-spy dump`), the log held `QueuePool limit of size 5 overflow 10 reached` errors, and Postgres
  showed 15 connections "idle in transaction".
* The pool (15 connections) is smaller than the thread pool (40), so overload makes threads queue for connections
  and abandoned requests keep waiting after their clients have gone. This is my reading of the evidence and has
  not been tested with a change.
* CPU was not the limit for ingest: the VM was mostly idle when it failed. The read scenarios used it fully
  (94% for `list`) before the API stalled.

## Reading it

1. **Anything that scans the big site's rows is the weak spot**: counts behind every list view, the filter
   menus, search and the dashboard. These match the table scans in [plans.md](plans.md).
2. **Anything that uses an index is fine**: `stats` showed no limit up to 150 per second.
3. **Overload does not degrade, it stops.** The same pool and thread setup turns a busy period into minutes
   of outage.
4. **A modest mixed load is enough to cause it.** 20 ingests plus a few readers per second, a rate ingest handles
   easily on its own, failed completely within a minute.

## To do before quoting numbers

* Repeat each scenario at least three times and keep the median.
* Rerun `ingest_hot` and `stats` with higher ranges, and `mixed` at lower rates to find its threshold.
* Tune Postgres (the default `shared_buffers` is 128 MB) and see how much that changes the read scenarios.
* Try more than one Uvicorn worker, and a larger pool, one change at a time. Then each fix from `plans.md` gets
  its own before and after against this baseline.
* The summaries in `bench/out/results/` contain the throwaway admin token, so do not publish them as they are.
