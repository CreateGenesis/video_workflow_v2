#!/usr/bin/env bash
# Start a throwaway cvgen stack on mock providers: database, admin user, sample workflows, API and worker.
# Usage: scripts/dev-up.sh <db-name> <port>     Stop with: scripts/dev-down.sh <db-name>
# Needs: PostgreSQL reachable at $PG_ADMIN_URL (default the local dev server), Python with requirements.
set -euo pipefail
NAME=${1:-cvgen_dev}
PORT=${2:-8080}
PY=${PY:-python3}
PG_ADMIN_URL=${PG_ADMIN_URL:-postgresql://postgres@127.0.0.1:55432/postgres}
STATE=${TMPDIR:-/tmp}/cvgen-dev-$NAME
mkdir -p "$STATE"
"$PY" - "$PG_ADMIN_URL" "$NAME" <<'PYEOF'
import sys, psycopg
with psycopg.connect(sys.argv[1], autocommit=True) as conn:
    conn.execute(f'DROP DATABASE IF EXISTS "{sys.argv[2]}" WITH (FORCE)')
    conn.execute(f'CREATE DATABASE "{sys.argv[2]}"')
PYEOF
BASE=${PG_ADMIN_URL%/*}
export CVGEN_DATABASE_URL="${BASE/postgresql:/postgresql+psycopg:}/$NAME"
export CVGEN_DATA="$STATE/data" CVGEN_SEED_MOCK=1 CVGEN_SECRET_KEY=${CVGEN_SECRET_KEY:-dev-secret} CVGEN_PUBLIC_BASE="http://127.0.0.1:$PORT"
"$PY" -m server.manage migrate
"$PY" -c "from server.app import bootstrap; bootstrap()"
"$PY" -m server.manage create-user admin --role admin --password adminpass1 >/dev/null
"$PY" -m server.manage seed-samples --publish
nohup "$PY" -m uvicorn server.app:app --host 127.0.0.1 --port "$PORT" >"$STATE/api.log" 2>&1 & echo $! >"$STATE/api.pid"
nohup "$PY" -m server.worker --threads 4 >"$STATE/worker.log" 2>&1 & echo $! >"$STATE/worker.pid"
for _ in $(seq 1 50); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 0.2; done
cat <<INFO
cvgen dev stack is up
  web/API : http://127.0.0.1:$PORT   (admin / adminpass1)
  env     : export CVGEN_DATABASE_URL=$CVGEN_DATABASE_URL CVGEN_DATA=$CVGEN_DATA CVGEN_SECRET_KEY=$CVGEN_SECRET_KEY
  logs    : $STATE/api.log $STATE/worker.log
INFO
