#!/bin/sh
# Step scenarios up until they break:
#   bench/baseline.sh http://10.0.0.5:18000              # all of them, about 30 minutes
#   bench/baseline.sh http://10.0.0.5:18000 search stats # just these
# Each run keeps its summary in bench/out/results/; bench/report.py turns one into a table per load step.
set -e
base=${1:?usage: bench/baseline.sh <api base url> [scenario ...]}
shift
cd "$(dirname "$0")"
secs=20

params() { # scenario -> start step steps (requests per second, as -e START / STEP / STEPS)
  case $1 in
    ingest_many) echo "50 50 10" ;;
    ingest_hot) echo "20 20 8" ;;
    list) echo "5 5 8" ;;
    filters) echo "10 10 8" ;;
    search) echo "2 2 8" ;;
    dashboard) echo "1 1 8" ;;
    stats) echo "10 20 8" ;;
    *) echo "unknown scenario $1" >&2; exit 2 ;;
  esac
}

# A scenario that overloads the API can leave it stuck for minutes. Wait until it answers, and say how long.
recover() {
  start=$(date +%s)
  until curl -fsS -m 2 -o /dev/null "$base/v1/api/health" 2>/dev/null; do
    [ $(($(date +%s) - start)) -gt 900 ] && { echo "API did not recover within 15 minutes"; exit 1; }
    sleep 5
  done
  echo "API answering again after $(($(date +%s) - start))s"
}

run() {
  if [ "$1" = mixed ]; then # steady load rather than steps; its rates are the MIX_* defaults
    echo "=== mixed $(date -u +%H:%M:%S)"
    ./run.sh mixed -e BASE_URL="$base" --quiet || echo "(k6 exit $?: thresholds crossed)"
    return
  fi
  set -- "$1" $(params "$1")
  echo "=== $1 ($2 + $3 x $4 per second, ${secs}s each) $(date -u +%H:%M:%S)"
  # k6 exits non-zero when a threshold is crossed, which is what happens at the breaking point.
  ./run.sh "$1" -e BASE_URL="$base" -e START="$2" -e STEP="$3" -e STEPS="$4" -e STEP_SECONDS=$secs --quiet ||
    echo "(k6 exit $?: thresholds crossed)"
}

if [ $# -gt 0 ]; then
  for s in "$@"; do run "$s"; done
else
  ./run.sh list -e BASE_URL="$base" -e START=5 -e STEP=0 -e STEPS=3 -e STEP_SECONDS=10 --quiet >/dev/null # warm-up
  for s in ingest_many ingest_hot list filters search dashboard stats; do
    run "$s"
    recover
    sleep 30
  done
  run mixed
fi
echo "=== done $(date -u +%H:%M:%S)"
