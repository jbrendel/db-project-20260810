#!/usr/bin/env bash
# Single pass/fail gate: backend (pytest) + frontend (vitest). Aggregates exit
# codes so it fails if EITHER suite fails (plans/INITIAL.md §18).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTEST="$ROOT/.venv/bin/pytest"
rc=0

echo "== backend (pytest) =="
if [ -x "$PYTEST" ]; then
  "$PYTEST" -q || rc=1
else
  "$ROOT/.venv/bin/python" -m pytest -q || rc=1
fi

echo "== frontend (vitest) =="
if [ ! -x frontend/node_modules/.bin/vitest ]; then
  echo "frontend deps missing — run 'npm install' in frontend/" >&2
  rc=1
else
  ( cd frontend && npm run test -- --run ) || rc=1
fi

exit "$rc"
