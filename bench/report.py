"""Print a k6 summary from bench/run.sh as a table per endpoint and load step.

    python3 bench/report.py bench/out/results/search-2026....json --start 2 --step 2 --step-seconds 20

--start / --step / --step-seconds must match the run (they are the -e values given to k6; the defaults
are the script's). "ramp to" is the rate each step ramps up to, so the average over a step is lower;
"sent/s" is the average k6 managed to send during the step; "failed" is the share of failed requests.
"""

import argparse
import json
import re

ap = argparse.ArgumentParser()
ap.add_argument("file")
ap.add_argument("--start", type=float, default=10)
ap.add_argument("--step", type=float, default=10)
ap.add_argument("--step-seconds", type=float, default=30)
args = ap.parse_args()

with open(args.file) as f:
    metrics = json.load(f)["metrics"]
rows = {}  # endpoint -> step -> stats
for key, m in metrics.items():
    hit = re.fullmatch(r"http_req_duration\{name:(\w+),step:(\d+)\}", key)
    if hit and "p(95)" in m:
        rows.setdefault(hit[1], {})[int(hit[2])] = m
sent = {int(k[-2]): m["count"] for k, m in metrics.items() if re.fullmatch(r"http_reqs\{step:\d+\}", k)}
failed = {
    int(k[-2]): m["value"] for k, m in metrics.items() if re.fullmatch(r"http_req_failed\{step:\d+\}", k)
}

for name, steps in rows.items():
    print(f"\n{name}")
    print(
        f"{'step':>4} {'ramp to/s':>9} {'sent/s':>8} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'failed':>7}"
    )
    for i in sorted(steps):
        m = steps[i]
        print(
            f"{i:>4} {args.start + args.step * i:>9.0f} {sent.get(i, 0) / args.step_seconds:>8.0f} "
            f"{m['med']:>8.0f} {m['p(95)']:>8.0f} {m['p(99)']:>8.0f} {failed.get(i, 0):>7.1%}"
        )
