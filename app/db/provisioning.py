"""
app/db/provisioning.py

Single source of truth for "make settings.DB_NAME exist and be at the
latest schema." Used by two callers that previously duplicated this logic:

  - scripts/run_migrations.py, invoked by the `migrate` compose service
    for every environment (dev/staging/prod *and* ENV=unittest) — see
    docker/docker-compose.yml.
  - tests/conftest.py, to rebuild a clean schema at the start of each test
    session after wiping it.

Because both paths call the same two functions, the schema pytest runs
against is always exactly what `alembic upgrade head` produces — never a
model-derived approximation that can drift from what real migrations do
(a manual `op.execute(...)`, a column rename, etc.).
"""

import logging

from sqlalchemy import create_engine, text

from alembic import command
from alembic.config import Config

from app.core.config import settings

logger = logging.getLogger(__name__)


def ensure_database_exists() -> None:
    """
    Creates settings.DB_NAME on the Postgres server if it doesn't already
    exist. Idempotent — safe to call on every startup and every test run.

    Connects to Postgres's always-present `postgres` maintenance database
    to issue CREATE DATABASE, since you can't connect to a database that
    doesn't exist yet to create it.
    """
    admin_url = (
        f"postgresql+psycopg2://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/postgres"
    )
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": settings.DB_NAME},
            ).fetchone()
            if not exists:
                logger.info("Database %r does not exist — creating it", settings.DB_NAME)
                conn.execute(text(f'CREATE DATABASE "{settings.DB_NAME}"'))
            else:
                logger.info("Database %r already exists — skipping creation", settings.DB_NAME)
    finally:
        admin_engine.dispose()


def run_migrations() -> None:
    """
    Applies every Alembic migration up to head against settings.DB_NAME.
    Alembic tracks its own applied-revisions table, so this is a no-op
    when the database is already at head.
    """
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
