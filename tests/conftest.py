import pytest
import pytest_asyncio

import redis.asyncio as redis
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

from app.core.redis_client import RedisClientManager
from app.db.session import engine as app_engine
from app.db.provisioning import ensure_database_exists, run_migrations

from app.main import app
from app.db.session import get_db
from app.core.config import settings

pytest_plugins = [
    "tests.fixtures.auth",
]
# ─── Guard ────────────────────────────────────────────────────────────────────
# Prevent tests from accidentally running against the real database.
if not settings.is_test:
    raise RuntimeError(
        f"Tests must run with ENV=unittest. "
        f"Current environment: '{settings.ENV}'. "
        f"Run tests via `make test` or pass ENV=unittest explicitly."
    )


# ─── Engine ───────────────────────────────────────────────────────────────────
# Use the application's engine so table creation and test sessions
# operate on the same connection pool and metadata.
engine = app_engine
sync_engine = create_engine(
    settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2"),
    pool_pre_ping=True,  # Checks connection health before using it from the pool
    pool_size=10,  # Max number of persistent connections
    max_overflow=20,  # Extra connections allowed beyond pool_size under load
)

TestingSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ─── Redis Fixture ────────────────────────────────────────────────────────────
@pytest_asyncio.fixture(autouse=True)
async def _flush_redis():
    """
    Runs before/after every test. Rate-limit counters and login-lockout
    state live in Redis keyed by IP/identifier — without this, tests that
    log in through `create_authenticated_user` (nearly every integration
    test file) would accumulate against the same fake test-client IP and
    eventually start tripping 429s unrelated to what the test is checking.

    Uses its own short-lived client rather than app.state.redis - a FLUSHDB affects
    the whole Redis DB server-side regardless of which client issues it, and this fixture
    runs for every test (including plain unittests that never touch the FastAPI app at all).
    """
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield
    await client.flushdb()
    await client.aclose()


# ─── Test DB Setup ────────────────────────────────────────────────────────────
def _reset_schema() -> None:
    """
    Drops and recreates the `public` schema — the fast, reliable way to
    wipe every table regardless of what migrations have added (indexes,
    views, custom types, etc. that Base.metadata wouldn't know about).
    Drops and recreates the `public` schema — the fast, reliable way to
    wipe every table regardless of what migrations have added (indexes,
    views, custom types, etc. that Base.metadata wouldn't know about).
    """
    with sync_engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """
    - Ensures propnest_unittest_db exists (idempotent — `migrate` has
      normally already done this, since `backend` depends on `migrate`
      completing successfully; this is just a defensive fallback for
      running pytest outside that dependency chain)
    - Resets to a clean, empty `public` schema
    - Applies every Alembic migration up to head, via the same
      app.db.provisioning helpers the `migrate` service uses — so tests
      run against exactly the schema real migrations produce, not a
      model-derived approximation
    - Resets the schema again after tests complete

    Safe to do because this only touches propnest_unittest_db, never propnest_db.
    """
    ensure_database_exists()
    _reset_schema()
    run_migrations()
    yield
    _reset_schema()


# ─── DB Fixture ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    connection = await engine.connect()

    # Outer transaction
    txn = await connection.begin()

    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
    )

    # First savepoint
    await session.begin_nested()

    @event.listens_for(session.sync_session, "after_transaction_end")
    def restart_savepoint(session_, trans):
        """
        Whenever production code calls session.commit(),
        SQLAlchemy releases the SAVEPOINT.

        Automatically start another SAVEPOINT so the
        remainder of the test is still isolated.
        """
        if txn.is_active and not session_.in_nested_transaction():
            session_.begin_nested()

    try:
        yield session
    finally:
        await session.close()
        await txn.rollback()
        await connection.close()


# ─── Client Fixture ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(db):

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.state.redis = RedisClientManager(
        url=settings.REDIS_URL,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
        health_check_interval=settings.REDIS_HEALTH_CHECK_INTERVAL,
    )

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await app.state.redis.close()
    app.dependency_overrides.clear()


class DummySavePoint:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


# ─── Mock DB Fixture ───────────────────────────────────────────────────────────
@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    db.begin_nested = AsyncMock(return_value=DummySavePoint())
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db
