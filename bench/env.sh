# Source this before running the API or worker for a benchmark:  . bench/env.sh
# It points at the throwaway database and cd's away from the repo so the developer's real .env
# (live mail credentials) is never read. Python finds the code through PYTHONPATH.
BENCH_REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
export DATABASE_URL="postgresql+psycopg://bench:bench@127.0.0.1:${BENCH_DB_PORT:-55433}/bench"
export ENVIRONMENT=development
export JWT_SECRET="bench-secret-bench-secret-bench-secret-123"
export REDIS_URL="${BENCH_REDIS_URL:-}"
export PYTHONPATH="$BENCH_REPO"
mkdir -p "$BENCH_REPO/bench/out/run" && cd "$BENCH_REPO/bench/out/run"
# One load generator is one IP and one key per site, so the default public rate limits would answer 429
# straight away. Lift them to measure the database path; set BENCH_DEFAULT_LIMITS=1 to measure with them.
if [ -z "${BENCH_DEFAULT_LIMITS:-}" ]; then
  export PUBLIC_IP_LIMIT=10000000 PUBLIC_KEY_LIMIT=10000000
fi
