import asyncio
import pytest

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.property import Property
from app.models.tenant import Tenant
from app.repositories.contract import contract_repo
from tests.factories import (
    make_property_model,
    make_tenant_model,
    make_contract,
)

@pytest.mark.asyncio
async def test_concurrent_create_active_contracts_fails_once():
    
    engine = create_async_engine(settings.DATABASE_URL)
    
    SessionLocal = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    successes = failures = 0
    async with SessionLocal() as setup_session:
        prop = await make_property_model(setup_session)
        tenant = await make_tenant_model(setup_session)
        
        await setup_session.commit()
        
        prop_id = prop.id
        tenant_id = tenant.id
        
    async def create_contract():
        async with SessionLocal() as session:
            try:
                await contract_repo.create(
                    session,
                    make_contract(
                        property_id=prop_id,
                        tenant_id=tenant_id,
                    ),
                )
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False
    
    try:
        results = await asyncio.gather(
            create_contract(),
            create_contract(),
        )
        
        successes = sum(results)
        failures = len(results) - successes
        
    finally:
        # cleanup created contracts, property, and tenant so subsequent tests
        # are not affected by rows inserted outside the test transaction.
        async with SessionLocal() as cleanup_session:
            contracts = await contract_repo.get_by_property(cleanup_session, prop_id)
            for c in contracts:
                await cleanup_session.delete(c)
            # Remove property and tenant created for the concurrency test
            p = await cleanup_session.get(Property, prop_id)
            if p:
                await cleanup_session.delete(p)
            t = await cleanup_session.get(Tenant, tenant_id)
            if t:
                await cleanup_session.delete(t)
            await cleanup_session.commit()
    
    assert successes == 1
    assert failures == 1
