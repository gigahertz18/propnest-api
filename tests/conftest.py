import pytest
import pytest_asyncio

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

from app.db.session import engine as app_engine

from app.main import app
from app.db.session import Base, get_db
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


# ─── Test DB Setup ────────────────────────────────────────────────────────────
def _ensure_test_db_exists() -> None:
    """
    Creates the test database if it doesn't exist.
    Connects to the postgres maintenance database to issue CREATE DATABASE.
    """
    admin_url = (
        f"postgresql+psycopg2://{settings.DB_USER}:{settings.DB_PASSWORD}" f"@{settings.DB_HOST}:{settings.DB_PORT}/postgres"
    )
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": settings.DB_NAME},
        ).fetchone()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{settings.DB_NAME}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """
    Runs once per test session.

    - Creates propnest_test database if it doesn't exist
    - Drops and recreates all tables for a clean slate
    - Drops all tables after tests complete

    Safe to do because this only touches propnest_test, never propnest_db.
    """
    _ensure_test_db_exists()
    Base.metadata.drop_all(bind=sync_engine)
    Base.metadata.create_all(bind=sync_engine)
    yield
    Base.metadata.drop_all(bind=sync_engine)


# ─── DB Fixture ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    connection = await engine.connect()
    
    #Outer transaction
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

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test"
    ) as client:
        yield client

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
