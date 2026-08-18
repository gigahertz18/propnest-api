import pytest
import pytest_asyncio
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.repositories.billing_record import billing_record_repo
from app.schemas.billing_record import BillingRecordCreate
from tests.factories import (
    make_billing_record,
    make_billing_record_model,
    make_contract_model,
    make_lease_model,
    make_manager_model,
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


@pytest.mark.asyncio
class TestCountForLease:
    async def test_counts_only_records_for_lease(self, db, lease, billing_record):
        result = await billing_record_repo.count_for_lease(db, lease.id)
        assert result == 1

    async def test_returns_zero_for_lease_with_no_records(self, db, lease):
        result = await billing_record_repo.count_for_lease(db, lease.id)
        assert result == 0


# ─── sum_outstanding / sum_outstanding_for_manager ───────────────────────────


@pytest.mark.asyncio
class TestSumOutstanding:
    async def test_sums_amount_due_for_unpaid_statuses(self, db, lease):
        await make_billing_record_model(
            db, lease_id=lease.id, period_start=date(2026, 8, 1), amount_due=1000.00, status="pending"
        )
        await make_billing_record_model(
            db, lease_id=lease.id, period_start=date(2026, 9, 1), amount_due=500.00, status="partially_paid"
        )
        await make_billing_record_model(
            db, lease_id=lease.id, period_start=date(2026, 10, 1), amount_due=2000.00, status="paid"
        )

        result = await billing_record_repo.sum_outstanding(db)

        assert result == Decimal("1500.00")

    async def test_includes_late_fee_when_charged(self, db, lease):
        await make_billing_record_model(
            db,
            lease_id=lease.id,
            period_start=date(2026, 8, 1),
            amount_due=1000.00,
            status="overdue",
            late_fee_applied=True,
            late_fee_amount_charged=100.00,
        )

        result = await billing_record_repo.sum_outstanding(db)

        assert result == Decimal("1100.00")

    async def test_returns_zero_when_no_unpaid_records(self, db, lease):
        await make_billing_record_model(
            db, lease_id=lease.id, period_start=date(2026, 8, 1), amount_due=1000.00, status="paid"
        )

        result = await billing_record_repo.sum_outstanding(db)

        assert result == Decimal("0")

    async def test_sum_outstanding_for_manager_scopes_to_owned_properties(self, db, tenant):
        manager = await make_manager_model(db)
        other_mgr = await make_manager_model(db, username="other_mgr_br", email="other_mgr_br@example.com")
        owned_property = await make_property_model(db, manager_id=manager.id)
        other_property = await make_property_model(db, name="Other Property", manager_id=other_mgr.id)
        owned_contract = await make_contract_model(db, property_id=owned_property.id, tenant_id=tenant.id)
        other_contract = await make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id)
        owned_lease = await make_lease_model(db, contract_id=owned_contract.id)
        other_lease = await make_lease_model(db, contract_id=other_contract.id)

        await make_billing_record_model(
            db, lease_id=owned_lease.id, period_start=date(2026, 8, 1), amount_due=1000.00, status="pending"
        )
        await make_billing_record_model(
            db, lease_id=other_lease.id, period_start=date(2026, 8, 1), amount_due=5000.00, status="pending"
        )

        result = await billing_record_repo.sum_outstanding_for_manager(db, manager.id)

        assert result == Decimal("1000.00")


# ─── get_unpaid_with_grace / get_unpaid_with_grace_for_manager ───────────────


@pytest.mark.asyncio
class TestGetUnpaidWithGrace:
    async def test_returns_unpaid_records_paired_with_their_leases_grace_period(self, db, lease, contract):
        record = await make_billing_record_model(
            db, lease_id=lease.id, period_start=date(2026, 8, 1), amount_due=1000.00, status="pending"
        )

        result = await billing_record_repo.get_unpaid_with_grace(db)

        assert len(result) == 1
        assert result[0][0].id == record.id
        assert result[0][1] == lease.grace_period_days

    async def test_excludes_paid_and_written_off_records(self, db, lease):
        await make_billing_record_model(
            db, lease_id=lease.id, period_start=date(2026, 8, 1), amount_due=1000.00, status="paid"
        )
        await make_billing_record_model(
            db, lease_id=lease.id, period_start=date(2026, 9, 1), amount_due=1000.00, status="written_off"
        )

        result = await billing_record_repo.get_unpaid_with_grace(db)

        assert result == []

    async def test_get_unpaid_with_grace_for_manager_scopes_to_owned_properties(self, db, tenant):
        manager = await make_manager_model(db)
        other_mgr = await make_manager_model(db, username="other_mgr_ug", email="other_mgr_ug@example.com")
        owned_property = await make_property_model(db, manager_id=manager.id)
        other_property = await make_property_model(db, name="Other Property", manager_id=other_mgr.id)
        owned_contract = await make_contract_model(db, property_id=owned_property.id, tenant_id=tenant.id)
        other_contract = await make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id)
        owned_lease = await make_lease_model(db, contract_id=owned_contract.id)
        other_lease = await make_lease_model(db, contract_id=other_contract.id)

        owned_record = await make_billing_record_model(
            db, lease_id=owned_lease.id, period_start=date(2026, 8, 1), amount_due=1000.00, status="pending"
        )
        await make_billing_record_model(
            db, lease_id=other_lease.id, period_start=date(2026, 8, 1), amount_due=1000.00, status="pending"
        )

        result = await billing_record_repo.get_unpaid_with_grace_for_manager(db, manager.id)

        assert len(result) == 1
        assert result[0][0].id == owned_record.id
