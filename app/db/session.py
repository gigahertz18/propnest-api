from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import NullPool
from app.core.config import settings

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
