import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.db.session import engine as app_engine

from app.main import app
from app.db.session import Base, get_db
from app.core.config import settings

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
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ─── Test DB Setup ────────────────────────────────────────────────────────────
def _ensure_test_db_exists() -> None:
    """
    Creates the test database if it doesn't exist.
    Connects to the postgres maintenance database to issue CREATE DATABASE.
    """
    admin_url = (
        f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}" f"@{settings.DB_HOST}:{settings.DB_PORT}/postgres"
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
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


# ─── DB Fixture ───────────────────────────────────────────────────────────────
@pytest.fixture(scope="function")
def db():
    """
    Each test function gets a DB session wrapped in a transaction.
    After the test, the outer transaction is rolled back — keeping the DB
    clean even though repository code internally calls db.commit().

    Savepoints (nested transactions) ensure inner commits don't break isolation.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ─── Client Fixture ───────────────────────────────────────────────────────────
@pytest.fixture(scope="function")
def client(db):
    """
    FastAPI TestClient with the real get_db dependency
    replaced by the test session.
    """

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
