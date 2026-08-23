#!/bin/sh
set -e
echo "[entrypoint] Waiting for database..."
python scripts/wait_for_db.py
exec "$@"
