#!/usr/bin/env python3
"""
scripts/wait_for_db.py

Run by docker/entrypoint.sh before `alembic upgrade head` (or, for the
`migrate` service, before anything else). Alembic has no retry logic of
its own — a not-yet-ready Postgres kills the container outright rather
than degrading gracefully. Checks that the Postgres *server* is reachable
rather than that the target database exists — see
app.db.session.wait_for_postgres_server for why (ENV=unittest's database
doesn't exist yet at this point; it's created later by tests/conftest.py).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import wait_for_postgres_server  # noqa: E402

if __name__ == "__main__":
    asyncio.run(wait_for_postgres_server())
