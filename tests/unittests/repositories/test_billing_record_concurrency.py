import asyncio
import pytest

from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.contract import Contract
from app.models.lease import Lease
from app.properties.models.property import Property
from app.crm.models.tenant import Tenant
from app.repositories.billing_record import billing_record_repo
from tests.factories import (
    make_property_model,
    make_tenant_model,
    make_contract_model,
    make_lease_model,
    make_billing_record,
)


@pytest.mark.asyncio
async def test_concurrent_generate_same_lease_and_period_only_one_succeeds():
    """Same class of race as test_lease_concurrency.py, guarded here by
    uq_billing_record_lease_id_period_start instead of contract_id."""

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
        lease = await make_lease_model(setup_session, contract_id=contract.id)

        await setup_session.commit()

        prop_id = prop.id
        tenant_id = tenant.id
        contract_id = contract.id
        lease_id = lease.id

    async def generate():
        async with SessionLocal() as session:
            try:
                from app.schemas.billing_record import BillingRecordCreate

                payload = BillingRecordCreate(**make_billing_record(lease_id=lease_id, period_start=date(2026, 8, 1)))
                await billing_record_repo.create(session, payload)
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    try:
        results = await asyncio.gather(
            generate(),
            generate(),
        )

        successes = sum(results)
        failures = len(results) - successes

    finally:
        async with SessionLocal() as cleanup_session:
            record = await billing_record_repo.get_by_lease_and_period(cleanup_session, lease_id, date(2026, 8, 1))
            if record:
                await cleanup_session.delete(record)
            lease_row = await cleanup_session.get(Lease, lease_id)
            if lease_row:
                await cleanup_session.delete(lease_row)
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
