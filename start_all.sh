#!/usr/bin/env bash
# Drumbeat local orchestrator (plans/INITIAL.md §4, §15).
# Starts Redis (Docker), Django, a Celery worker with embedded beat, and Vite,
# each on a dynamically chosen free port propagated via env vars. Ctrl-C (or any
# exit) tears everything down, including the run-scoped Redis container.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"
LOG_DIR="$ROOT/logs"
REDIS_CONTAINER="drumbeat-redis-$$"
RESET_DB=0

for arg in "$@"; do
  case "$arg" in
    --reset-db) RESET_DB=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

# --- Prerequisite checks (fail loud; §15) ---------------------------------
[ -x "$PYTHON" ] || die "No .venv found. Create it: uv venv --python 3.13 && \
uv pip install -r requirements.txt"
command -v docker >/dev/null 2>&1 || die "Docker is required for Redis but was \
not found on PATH."
"$PYTHON" -c "import django, celery, rest_framework, redis" 2>/dev/null \
  || die "Python dependencies missing. Run: uv pip install -r requirements.txt"
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  die "frontend/node_modules missing. Run: (cd frontend && npm install)"
fi

mkdir -p "$LOG_DIR"

# --- --reset-db: only while services are stopped (§15) --------------------
if [ "$RESET_DB" = "1" ]; then
  if [ -n "$(docker ps -q --filter name=drumbeat-redis- 2>/dev/null)" ]; then
    echo "Refusing --reset-db: a drumbeat Redis container is running." >&2
    exit 1
  fi
  docker ps -aq --filter name=drumbeat-redis- 2>/dev/null | xargs -r docker rm -f
  rm -f "$ROOT/db.sqlite3" "$ROOT/db.sqlite3-wal" "$ROOT/db.sqlite3-shm" \
        "$ROOT"/celerybeat-schedule*
  echo "Reset: removed SQLite DB (+ wal/shm) and beat schedule."
fi

# --- Free-port discovery (bind-check + short retry to reduce TOCTOU) -------
find_free_port() {
  local port tries=0
  while [ "$tries" -lt 50 ]; do
    port="$("$PYTHON" - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"
    if ! (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      echo "$port"; return 0
    fi
    tries=$((tries + 1))
  done
  die "Could not find a free port after 50 attempts."
}

REDIS_PORT="$(find_free_port)"
DJANGO_PORT="$(find_free_port)"
VITE_PORT="$(find_free_port)"
REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/0"
export REDIS_PORT DJANGO_PORT VITE_PORT REDIS_URL

echo "Ports -> Redis:${REDIS_PORT}  Django:${DJANGO_PORT}  Vite:${VITE_PORT}"
echo "REDIS_URL=${REDIS_URL}"

# --- Cleanup trap: kill children and remove the run-scoped container -------
CHILD_PIDS=()
cleanup() {
  trap - SIGINT SIGTERM EXIT
  echo ""
  echo "Shutting down..."
  for pid in "${CHILD_PIDS[@]}"; do
    kill "$pid" 2>/dev/null
  done
  wait 2>/dev/null
  docker rm -f "$REDIS_CONTAINER" >/dev/null 2>&1
  echo "Done."
}
trap cleanup SIGINT SIGTERM EXIT

# --- Start Redis (run-scoped, collision-free name) ------------------------
docker rm -f "$REDIS_CONTAINER" >/dev/null 2>&1
docker run -d --name "$REDIS_CONTAINER" \
  -p "127.0.0.1:${REDIS_PORT}:6379" redis:7-alpine \
  >/dev/null 2>&1 || die "Failed to start Redis container."

echo -n "Waiting for Redis"
for _ in $(seq 1 30); do
  if docker exec "$REDIS_CONTAINER" redis-cli ping 2>/dev/null | grep -q PONG
  then
    echo " ready."
    break
  fi
  echo -n "."
  sleep 0.5
done
docker exec "$REDIS_CONTAINER" redis-cli ping 2>/dev/null | grep -q PONG \
  || die "Redis did not become ready."

# --- Migrate, then start the services -------------------------------------
"$PYTHON" manage.py migrate >>"$LOG_DIR/django.log" 2>&1 \
  || die "Database migration failed (see logs/django.log)."

"$PYTHON" manage.py runserver "127.0.0.1:${DJANGO_PORT}" \
  >>"$LOG_DIR/django.log" 2>&1 &
CHILD_PIDS+=("$!")

(
  cd "$ROOT/frontend" && npm run dev -- --port "$VITE_PORT" \
    >>"$LOG_DIR/vite.log" 2>&1
) &
CHILD_PIDS+=("$!")

# --- Supervise the Celery worker (§5.5/§15): restart if it exits ----------
supervise_worker() {
  while true; do
    "$ROOT/.venv/bin/celery" -A drumbeat worker -B \
      --loglevel=info >>"$LOG_DIR/celery.log" 2>&1
    echo "$(date '+%F %T') celery worker exited; restarting" \
      >>"$LOG_DIR/celery.log"
    sleep 1
  done
}
supervise_worker &
CHILD_PIDS+=("$!")

echo "All services started. Tailing logs (Ctrl-C to stop)."
touch "$LOG_DIR/django.log" "$LOG_DIR/celery.log" "$LOG_DIR/vite.log"
tail -f "$LOG_DIR/django.log" "$LOG_DIR/celery.log" "$LOG_DIR/vite.log" &
CHILD_PIDS+=("$!")

wait
