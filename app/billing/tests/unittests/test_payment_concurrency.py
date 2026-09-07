import asyncio
import pytest

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.billing.repositories.payment import payment_repo


@pytest.mark.asyncio
async def test_concurrent_next_cash_reference_number_calls_never_collide():
    """cash_reference_number_seq is a native Postgres sequence — nextval()
    is atomic under MVCC and immune to the classic read-then-increment race
    an app-level max()+1 approach would have. This exercises that guarantee
    with real concurrent connections/sessions, mirroring the pattern in
    test_billing_record_concurrency.py, rather than only asserting it by
    inspecting the migration."""
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def allocate():
        async with SessionLocal() as session:
            value = await payment_repo.next_cash_reference_number(session)
            await session.commit()
            return value

    try:
        results = await asyncio.gather(*(allocate() for _ in range(10)))
    finally:
        await engine.dispose()

    assert len(results) == 10
    assert len(set(results)) == 10
