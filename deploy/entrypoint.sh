#!/bin/sh
# Usage: entrypoint.sh api | worker [worker args...]
set -e
mkdir -p "${CVGEN_DATA:-/data}"
chown cvgen:cvgen "${CVGEN_DATA:-/data}"
role="${1:-api}"
[ "$#" -gt 0 ] && shift
if [ "$role" = "api" ]; then
  su -s /bin/sh cvgen -c 'python -m server.manage migrate'
  exec su -s /bin/sh cvgen -c "exec uvicorn server.app:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips='*'"
fi
if [ "$role" = "worker" ]; then
  exec su -s /bin/sh cvgen -c "exec python -m server.worker $*"
fi
exec "$role" "$@"
