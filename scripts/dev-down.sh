#!/usr/bin/env bash
# Stop the stack started by scripts/dev-up.sh <db-name>.
NAME=${1:-cvgen_dev}
STATE=${TMPDIR:-/tmp}/cvgen-dev-$NAME
for proc in api worker; do
  [ -f "$STATE/$proc.pid" ] && kill "$(cat "$STATE/$proc.pid")" 2>/dev/null && rm -f "$STATE/$proc.pid"
done
echo "stopped $NAME"
