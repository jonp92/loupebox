#!/bin/sh
# Step every scenario up until it breaks, with a cool-down between runs:
#   bench/baseline.sh http://10.0.0.5:18000
# Takes about 30 minutes. Each run keeps its summary in bench/out/results/. Start `vmstat -t 5` on the
# system under test first if you want CPU steal and load alongside (see bench/README.md).
set -e
base=${1:?usage: bench/baseline.sh <api base url>}
cd "$(dirname "$0")"
secs=20
run() { # scenario, start, step, steps
  echo "=== $1 ($2 + $3 x $4 per second, ${secs}s each) $(date -u +%H:%M:%S)"
  ./run.sh "$1" -e BASE_URL="$base" -e START="$2" -e STEP="$3" -e STEPS="$4" -e STEP_SECONDS=$secs --quiet
  sleep 30
}
echo "=== warm-up"
./run.sh list -e BASE_URL="$base" -e START=5 -e STEP=0 -e STEPS=3 -e STEP_SECONDS=10 --quiet >/dev/null
run ingest_many 50 50 10
run ingest_hot 20 20 8
run list 5 5 8
run filters 10 10 8
run search 2 2 8
run dashboard 1 1 8
run stats 10 20 8
echo "=== mixed $(date -u +%H:%M:%S)"
./run.sh mixed -e BASE_URL="$base" --quiet
echo "=== done $(date -u +%H:%M:%S)"
