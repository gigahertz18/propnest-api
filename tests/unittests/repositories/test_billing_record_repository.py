import pytest
import pytest_asyncio
import uuid
from datetime import date

from sqlalchemy.exc import IntegrityError

from app.repositories.billing_record import billing_record_repo
from app.schemas.billing_record import BillingRecordCreate
from tests.factories import (
    make_billing_record,
    make_billing_record_model,
    make_contract_model,
    make_lease_model,
    make_property_model,
    make_tenant_model,
)

# ─── Shared fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def property_(db):
    return await make_property_model(db)


@pytest_asyncio.fixture
async def tenant(db):
    return await make_tenant_model(db)


@pytest_asyncio.fixture
async def contract(db, property_, tenant):
    return await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)


@pytest_asyncio.fixture
async def lease(db, contract):
    return await make_lease_model(db, contract_id=contract.id)


@pytest_asyncio.fixture
async def billing_record(db, lease):
    return await make_billing_record_model(db, lease_id=lease.id, period_start=date(2026, 8, 1))


# ─── get_by_lease_and_period ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetByLeaseAndPeriod:
    async def test_returns_match(self, db, lease, billing_record):
        result = await billing_record_repo.get_by_lease_and_period(db, lease.id, date(2026, 8, 1))
        assert result is not None
        assert result.id == billing_record.id

    async def test_returns_none_when_no_match(self, db, lease):
        result = await billing_record_repo.get_by_lease_and_period(db, lease.id, date(2026, 9, 1))
        assert result is None


# ─── create ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestBillingRecordRepositoryCreate:
    async def test_creates_billing_record_successfully(self, db, lease):
        payload = BillingRecordCreate(**make_billing_record(lease_id=lease.id, period_start=date(2026, 8, 1)))
        result = await billing_record_repo.create(db, payload)
        assert result.id is not None
        assert result.lease_id == lease.id
        assert result.period_start == date(2026, 8, 1)
        assert result.status == "pending"

    async def test_duplicate_lease_and_period_raises_integrity_error(self, db, lease, billing_record):
        """Idempotency guard: uq_billing_record_lease_id_period_start."""
        payload = BillingRecordCreate(**make_billing_record(lease_id=lease.id, period_start=date(2026, 8, 1)))
        with pytest.raises(IntegrityError):
            await billing_record_repo.create(db, payload)

    async def test_same_lease_different_period_is_allowed(self, db, lease, billing_record):
        payload = BillingRecordCreate(**make_billing_record(lease_id=lease.id, period_start=date(2026, 9, 1)))
        result = await billing_record_repo.create(db, payload)
        assert result.id is not None


# ─── get_by_id / get_all_for_lease ────────────────────────────────────────────


@pytest.mark.asyncio
class TestBillingRecordRepositoryGetById:
    async def test_returns_billing_record_when_found(self, db, billing_record):
        result = await billing_record_repo.get_by_id(db, billing_record.id)
        assert result is not None
        assert result.id == billing_record.id

    async def test_returns_none_when_not_found(self, db):
        result = await billing_record_repo.get_by_id(db, uuid.uuid4())
        assert result is None


@pytest.mark.asyncio
class TestGetAllForLease:
    async def test_returns_only_records_for_lease(self, db, lease, billing_record):
        result = await billing_record_repo.get_all_for_lease(db, lease.id)
        assert len(result) == 1
        assert result[0].id == billing_record.id

    async def test_returns_empty_list_for_lease_with_no_records(self, db, lease):
        result = await billing_record_repo.get_all_for_lease(db, lease.id)
        assert result == []
