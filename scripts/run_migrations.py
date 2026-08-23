#!/usr/bin/env python3
"""
scripts/run_migrations.py

Entry point for the `migrate` compose service (see
docker/docker-compose.yml). Ensures the target database (settings.DB_NAME)
exists, then applies every Alembic migration up to head.

Deliberately environment-agnostic — the same two calls run for dev/staging/
prod *and* ENV=unittest, so there's exactly one code path that provisions a
database's schema, not one for "real" environments and a second,
model-derived one for tests. See app/db/provisioning.py.

Usage (inside the migrate container):
    python scripts/run_migrations.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.provisioning import ensure_database_exists, run_migrations  # noqa: E402

if __name__ == "__main__":
    ensure_database_exists()
    run_migrations()
