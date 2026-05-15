from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # Checks connection health before using it from the pool
    pool_size=10,  # Max number of persistent connections
    max_overflow=20,  # Extra connections allowed beyond pool_size under load
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """All SQLAlchemy models inherit from this."""

    pass


def get_db():
    """
    FastAPI dependency — yields a DB session per request
    and ensures it's closed afterward.

    Usage in a route:
        def my_route(db: Session = Depends(get_db)):
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
