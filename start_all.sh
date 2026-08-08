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
# Deterministic ports: each service prefers a fixed, non-standard port and only
# moves to the NEXT sequential free port if that one is taken — so the Vite URL
# (and Django/Redis) stay stable across restarts and you don't re-copy the FE
# URL every time. Override a preference with DRUMBEAT_{REDIS,DJANGO,VITE}_PORT.
PREFERRED_REDIS_PORT="${DRUMBEAT_REDIS_PORT:-6390}"
PREFERRED_DJANGO_PORT="${DRUMBEAT_DJANGO_PORT:-8390}"
PREFERRED_VITE_PORT="${DRUMBEAT_VITE_PORT:-5390}"

_port_is_free() {  # <port> -> 0 if nothing is listening on 127.0.0.1:<port>
  ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

# Try <preferred>, then preferred+1, +2, ... (deterministic, never random),
# skipping any port passed as a later argument (already assigned this run).
find_port_from() {
  local preferred="$1"; shift
  local exclude=" $* " port
  for ((port = preferred; port < preferred + 100; port++)); do
    if [[ "$exclude" != *" $port "* ]] && _port_is_free "$port"; then
      echo "$port"; return 0
    fi
  done
  die "No free port found near ${preferred}."
}

REDIS_PORT="$(find_port_from "$PREFERRED_REDIS_PORT")"
DJANGO_PORT="$(find_port_from "$PREFERRED_DJANGO_PORT" "$REDIS_PORT")"
VITE_PORT="$(find_port_from "$PREFERRED_VITE_PORT" "$REDIS_PORT" "$DJANGO_PORT")"
REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/0"
export REDIS_PORT DJANGO_PORT VITE_PORT REDIS_URL

echo "Ports -> Redis:${REDIS_PORT}  Django:${DJANGO_PORT}  Vite:${VITE_PORT}"
echo "Open the app at: http://localhost:${VITE_PORT}"
echo "REDIS_URL=${REDIS_URL}"

# --- Cleanup trap: kill child process GROUPS and remove the container ------
# Each long-lived service is launched with `setsid` so it leads its own process
# group (pgid == pid). Killing the negative pid signals the whole group, so
# grandchildren (celery prefork children, vite's node, runserver's autoreload
# child) are terminated too — a plain `kill <pid>` would orphan them (§15).
GROUP_PIDS=()
start_service() {  # start_service <logfile> <command...>
  local log="$1"; shift
  setsid "$@" >>"$log" 2>&1 &
  GROUP_PIDS+=("$!")
}
cleanup() {
  trap - SIGINT SIGTERM EXIT
  echo ""
  echo "Shutting down..."
  for pid in "${GROUP_PIDS[@]}"; do
    kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
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

start_service "$LOG_DIR/django.log" \
  "$PYTHON" manage.py runserver "127.0.0.1:${DJANGO_PORT}"

start_service "$LOG_DIR/vite.log" \
  bash -c 'cd "$1"/frontend && exec npm run dev -- --port "$2"' \
  _ "$ROOT" "$VITE_PORT"

# --- Supervise the Celery worker (§5.5/§15): restart if it exits ----------
# The whole supervise loop runs in its own process group (via start_service +
# setsid), so cleanup's group-kill stops both the loop and the live worker.
start_service "$LOG_DIR/celery.log" \
  bash -c 'while true; do
    "$1/.venv/bin/celery" -A drumbeat worker -B --loglevel=info
    echo "$(date "+%F %T") celery worker exited; restarting"
    sleep 1
  done' _ "$ROOT"

echo "All services started. Tailing logs (Ctrl-C to stop)."
touch "$LOG_DIR/django.log" "$LOG_DIR/celery.log" "$LOG_DIR/vite.log"
tail -f "$LOG_DIR/django.log" "$LOG_DIR/celery.log" "$LOG_DIR/vite.log" &
GROUP_PIDS+=("$!")

wait
