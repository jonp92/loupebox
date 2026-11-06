# Source this to run the API from a Python checkout instead of Docker:  . bench/env.sh
# It loads bench/bench.env, points at the throwaway database, and cd's away from the repo so a real .env
# (live mail credentials) is never read. Python finds the code through PYTHONPATH.
BENCH_REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
set -a
. "$BENCH_REPO/bench/bench.env"
set +a
export DATABASE_URL="postgresql+psycopg://bench:bench@127.0.0.1:${BENCH_DB_PORT:-55433}/bench"
[ -n "${BENCH_REDIS_URL:-}" ] && export REDIS_URL="$BENCH_REDIS_URL"
export PYTHONPATH="$BENCH_REPO"
mkdir -p "$BENCH_REPO/bench/out/run" && cd "$BENCH_REPO/bench/out/run"
