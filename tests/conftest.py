import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app
from app.db.session import Base, get_db
from app.core.config import settings


# ─── Engine ───────────────────────────────────────────────────────────────────
# Use the real PostgreSQL DB — it's available inside Docker where tests run.
# NullPool ensures connections are not reused across tests.
engine = create_engine(settings.DATABASE_URL, poolclass=NullPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ─── Session Fixture ──────────────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """
    Runs once per test session.
    Creates all tables cleanly, yields, then drops them.

    Uses checkfirst=True so it's safe to run even if some tables
    already exist from Alembic migrations.
    """
    # Drop enum types that may already exist from Alembic migrations
    # to avoid "type already exists" conflicts on create_all
    with engine.connect() as conn:
        conn.execute(text("DROP TYPE IF EXISTS rentaltype CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS propertystatus CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS userrole CASCADE"))
        conn.commit()

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    yield

    # Clean up after all tests are done
    # Run `make migrate-up` after tests to restore migration state
    Base.metadata.drop_all(bind=engine)


# ─── DB Fixture ───────────────────────────────────────────────────────────────
@pytest.fixture(scope="function")
def db():
    """
    Each test gets a DB session wrapped in a transaction.
    After the test, the transaction is rolled back — keeping the DB clean
    even though the repository code internally calls db.commit().

    Uses savepoints (nested transactions) so inner commits don't break isolation.
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
    FastAPI TestClient with the test DB session injected.
    Replaces the real get_db dependency with the test session.
    """
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
