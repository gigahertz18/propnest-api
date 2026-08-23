import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import NullPool
from app.core.config import settings

logger = logging.getLogger(__name__)

if settings.is_test:
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=False,  # Checks connection health before using it from the pool
        poolclass=NullPool,
    )
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,  # Checks connection health before using it from the pool
        pool_size=10,  # Max number of persistent connections
        max_overflow=20,  # Extra connections allowed beyond pool_size under load
    )

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """All SQLAlchemy models inherit from this."""

    pass


async def get_db():
    """
    FastAPI dependency — yields a DB async session per request

    Transaction ownership lives in the service layer:
    - service methods commit after successful writes
    - this dependency only rolls back on exception and closes the session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def _wait_for_connection(target_engine, max_retries: int, retry_interval: int, label: str) -> None:
    for attempt in range(1, max_retries + 1):
        try:
            async with target_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("%s is ready", label)
            return
        except Exception as e:
            if attempt == max_retries:
                logger.error(
                    "%s not available after %d attempts. Last error: %s",
                    label,
                    max_retries,
                    e,
                )
                raise RuntimeError(f"Could not connect to {label.lower()} after {max_retries} attempts.") from e

            logger.warning(
                "%s not ready (attempt %d/%d) — retrying in %ds...",
                label,
                attempt,
                max_retries,
                retry_interval,
            )
            await asyncio.sleep(retry_interval)


async def wait_for_db(max_retries: int | None = None, retry_interval: int | None = None) -> None:
    """
    Retries the DB connection until PostgreSQL is ready or max retries
    exceeded. Used by app.main's lifespan so the API doesn't crash on a
    slow-starting Postgres. Defaults come from settings, matching the
    config-class-tunable pattern used everywhere else in this file.
    """
    max_retries = max_retries if max_retries is not None else settings.DB_MAX_RETRIES
    retry_interval = retry_interval if retry_interval is not None else settings.DB_RETRY_INTERVAL
    await _wait_for_connection(engine, max_retries, retry_interval, label="Database")


async def wait_for_postgres_server(max_retries: int | None = None, retry_interval: int | None = None) -> None:
    """
    Used by scripts/wait_for_db.py via docker/entrypoint.sh, before the
    `migrate` service's command runs (see docker/docker-compose.yml). Neither
    Alembic nor app.db.provisioning.ensure_database_exists has retry logic of
    its own — a not-yet-ready Postgres server would otherwise kill the
    container outright. Deliberately connects to Postgres's always-present
    `postgres` maintenance database rather than settings.DATABASE_URL's
    target: the target database (settings.DB_NAME) may not exist yet at this
    point for any environment — creating it is app.db.provisioning's job, not
    this function's. This only needs to confirm the Postgres *server* itself
    is reachable.
    """
    max_retries = max_retries if max_retries is not None else settings.DB_MAX_RETRIES
    retry_interval = retry_interval if retry_interval is not None else settings.DB_RETRY_INTERVAL

    maintenance_url = (
        f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/postgres"
    )
    maintenance_engine = create_async_engine(maintenance_url, poolclass=NullPool)
    try:
        await _wait_for_connection(maintenance_engine, max_retries, retry_interval, label="Postgres server")
    finally:
        await maintenance_engine.dispose()
