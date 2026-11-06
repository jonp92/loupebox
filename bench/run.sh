#!/bin/sh
# Run one k6 scenario and keep its summary:  bench/run.sh <scenario> [-e NAME=value ...]
# Needs the API running (see bench/README.md) and bench/out/sites.json from the seeder.
# Uses k6 if it is installed, otherwise the grafana/k6 image (uncapped, on the host network).
set -e
scenario=${1:?usage: bench/run.sh <scenario> [k6 args]}
shift
cd "$(dirname "$0")"
mkdir -p out/results
name="$scenario-$(date -u +%Y%m%dT%H%M%SZ)"
if command -v k6 >/dev/null 2>&1; then
  k6() { command k6 "$@"; }
else
  k6() { docker run --rm -i --network host --user "$(id -u):$(id -g)" -v "$PWD:/bench" -w /bench grafana/k6:latest "$@"; }
fi
k6 run -e SCENARIO="$scenario" --summary-export "out/results/$name.json" "$@" k6/loupebox.js
echo "Summary: $PWD/out/results/$name.json"
