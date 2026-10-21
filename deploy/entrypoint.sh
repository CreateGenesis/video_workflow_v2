#!/bin/sh
set -e
mkdir -p /data
chown cvgen:cvgen /data
exec su -s /bin/sh cvgen -c 'exec uvicorn server.app:app --host 0.0.0.0 --port 8080'
