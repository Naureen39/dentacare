#!/bin/bash
# Run the load scenarios against a throw away copy of the API on port 8199.
#
#   perf/run.sh
#
# Needs: the compose stack's database and Redis running, a database to test against
# (default meridian_perf: restore a backup into it, see docs/runbook.md), uv, and Docker for k6.
# Rate limits are raised for the test server only. The test server is stopped at the end.
set -euo pipefail
cd "$(dirname "$0")/.."

DB="${PERF_DB:-meridian_perf}"
PORT="${PERF_PORT:-8199}"
USER_="${POSTGRES_USER:-meridian}"; PASS_="${POSTGRES_PASSWORD:-meridian}"
export DATABASE_URL="postgresql+asyncpg://$USER_:$PASS_@127.0.0.1:5432/$DB"
export REDIS_URL="redis://127.0.0.1:6379/1"   # a separate Redis database from the app's
export JWT_ACCESS_MINUTES=120
export LOG_LEVEL=WARNING   # one log line per request would be most of the work on a laptop
for name in LOGIN_PER_MINUTE ACCOUNT_EMAIL_PER_HOUR PUBLIC_BOOKING_PER_HOUR CONTACT_PER_HOUR CHAT_PER_MINUTE; do
  export "RATE_LIMIT_$name=1000000"
done

cd backend
TOKEN="$(uv run --quiet python -m scripts.mint_admin_token 2>/dev/null | tail -n 1)"
# The access log goes to a file: printing every request to the terminal costs more than the request.
uv run python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --workers "${PERF_WORKERS:-4}" --log-level warning > "${PERF_LOG:-${TMPDIR:-/tmp}/meridian-perf-server.log}" 2>&1 &
SERVER=$!
cleanup() {
  # Stop only the server started here (and its workers), never other processes.
  if command -v taskkill > /dev/null 2>&1; then taskkill //PID "$SERVER" //T //F > /dev/null 2>&1 || true
  else kill "$SERVER" 2>/dev/null || true; fi
}
trap cleanup EXIT

for _ in $(seq 1 90); do
  curl -fs "http://127.0.0.1:$PORT/ready" > /dev/null && break
  sleep 1
done
curl -fs "http://127.0.0.1:$PORT/ready" > /dev/null || { echo "the test server did not start" >&2; exit 1; }

cd ..
HOST="host.docker.internal"
MSYS_NO_PATHCONV=1 docker run --rm --add-host=host.docker.internal:host-gateway \
  -e BASE_URL="http://$HOST:$PORT" -e ADMIN_TOKEN="$TOKEN" -e DURATION="${DURATION:-30s}" \
  -v "$PWD/perf/k6:/scripts:ro" grafana/k6:latest run /scripts/meridian.js "$@"
