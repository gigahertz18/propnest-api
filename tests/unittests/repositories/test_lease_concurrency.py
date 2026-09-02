import asyncio
import pytest

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.contract import Contract
from app.properties.models.property import Property
from app.models.tenant import Tenant
from app.repositories.lease import lease_repo
from tests.factories import (
    make_property_model,
    make_tenant_model,
    make_contract_model,
    make_lease,
)


@pytest.mark.asyncio
async def test_concurrent_create_leases_for_same_contract_fails_once():
    """Same class of race as test_contract_concurrency.py, guarded here by
    the plain unique FK (uq_lease_contract_id) instead of a partial index."""

    engine = create_async_engine(settings.DATABASE_URL)

    SessionLocal = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with SessionLocal() as setup_session:
        prop = await make_property_model(setup_session)
        tenant = await make_tenant_model(setup_session)
        contract = await make_contract_model(setup_session, property_id=prop.id, tenant_id=tenant.id)

        await setup_session.commit()

        prop_id = prop.id
        tenant_id = tenant.id
        contract_id = contract.id

    async def create_lease():
        async with SessionLocal() as session:
            try:
                from app.schemas.lease import LeaseCreate

                await lease_repo.create(session, LeaseCreate(**make_lease(contract_id=contract_id)))
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    try:
        results = await asyncio.gather(
            create_lease(),
            create_lease(),
        )

        successes = sum(results)
        failures = len(results) - successes

    finally:
        async with SessionLocal() as cleanup_session:
            lease = await lease_repo.get_by_contract(cleanup_session, contract_id)
            if lease:
                await cleanup_session.delete(lease)
            c = await cleanup_session.get(Contract, contract_id)
            if c:
                await cleanup_session.delete(c)
            p = await cleanup_session.get(Property, prop_id)
            if p:
                await cleanup_session.delete(p)
            t = await cleanup_session.get(Tenant, tenant_id)
            if t:
                await cleanup_session.delete(t)
            await cleanup_session.commit()

    assert successes == 1
    assert failures == 1
