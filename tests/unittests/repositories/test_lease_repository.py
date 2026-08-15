import pytest
import pytest_asyncio
import uuid
from datetime import date, timedelta

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.repositories.lease import lease_repo
from app.schemas.lease import LeaseCreate, LeaseUpdate
from app.models.lease import BillingCycle, RenewalOption
from tests.factories import (
    make_lease,
    make_lease_model,
    make_contract_model,
    make_property_model,
    make_tenant_model,
    make_manager_model,
)

# ─── Shared fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def manager(db):
    return await make_manager_model(db)


@pytest_asyncio.fixture
async def property_(db):
    return await make_property_model(db)


@pytest_asyncio.fixture
async def tenant(db):
    return await make_tenant_model(db)


@pytest_asyncio.fixture
async def contract(db, property_, tenant):
    """A persisted long-term Contract for FK references."""
    return await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)


@pytest_asyncio.fixture
async def active_lease(db, contract):
    return await make_lease_model(db, contract_id=contract.id)


# ─── get_all ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLeaseRepositoryGetAll:
    async def test_returns_empty_list_when_no_leases(self, db):
        result = await lease_repo.get_all(db)
        assert result == []

    async def test_returns_all_leases(self, db, property_, tenant):
        c1 = await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        other_property = await make_property_model(db, name="Other Property")
        c2 = await make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id)
        await make_lease_model(db, contract_id=c1.id)
        await make_lease_model(db, contract_id=c2.id)
        result = await lease_repo.get_all(db)
        assert len(result) == 2


# ─── get_by_id ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLeaseRepositoryGetById:
    async def test_returns_lease_when_found(self, db, active_lease):
        result = await lease_repo.get_by_id(db, active_lease.id)
        assert result is not None
        assert result.id == active_lease.id

    async def test_returns_none_when_not_found(self, db):
        result = await lease_repo.get_by_id(db, uuid.uuid4())
        assert result is None


# ─── get_by_contract ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLeaseRepositoryGetByContract:
    async def test_returns_lease_for_contract(self, db, contract, active_lease):
        result = await lease_repo.get_by_contract(db, contract.id)
        assert result is not None
        assert result.id == active_lease.id

    async def test_returns_none_when_no_lease_for_contract(self, db, contract):
        result = await lease_repo.get_by_contract(db, contract.id)
        assert result is None

    async def test_returns_none_for_nonexistent_contract_id(self, db):
        result = await lease_repo.get_by_contract(db, uuid.uuid4())
        assert result is None


# ─── create ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLeaseRepositoryCreate:
    async def test_creates_lease_successfully(self, db, contract):
        payload = LeaseCreate(**make_lease(contract_id=contract.id))
        result = await lease_repo.create(db, payload)
        assert result.id is not None
        assert result.contract_id == contract.id
        assert result.monthly_rent == 15000.00
        assert result.due_day == 5
        assert result.status == "ACTIVE"
        assert result.billing_cycle == BillingCycle.monthly
        assert result.renewal_option == RenewalOption.none

    async def test_created_lease_is_persisted(self, db, contract):
        payload = LeaseCreate(**make_lease(contract_id=contract.id, monthly_rent=20000.00))
        created = await lease_repo.create(db, payload)
        fetched = await lease_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.monthly_rent == 20000.00

    async def test_security_deposit_is_optional(self, db, contract):
        payload = LeaseCreate(**make_lease(contract_id=contract.id, security_deposit=None))
        result = await lease_repo.create(db, payload)
        assert result.security_deposit is None

    async def test_end_date_is_optional(self, db, contract):
        payload = LeaseCreate(**make_lease(contract_id=contract.id, end_date=None))
        result = await lease_repo.create(db, payload)
        assert result.end_date is None

    async def test_late_fee_percent_variant(self, db, contract):
        payload = LeaseCreate(**make_lease(contract_id=contract.id, late_fee_amount=None, late_fee_percent=5.0))
        result = await lease_repo.create(db, payload)
        assert result.late_fee_amount is None
        assert result.late_fee_percent == 5.0

    async def test_duplicate_contract_id_raises_integrity_error(self, db, contract, active_lease):
        """1:1 Lease<->Contract enforced by uq_lease_contract_id."""
        payload = LeaseCreate(**make_lease(contract_id=contract.id))
        with pytest.raises(IntegrityError):
            await lease_repo.create(db, payload)


class TestLeaseRepositoryCreateEdgeCases:
    def test_monthly_rent_zero_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            LeaseCreate(**make_lease(contract_id=contract.id, monthly_rent=0))

    def test_monthly_rent_negative_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            LeaseCreate(**make_lease(contract_id=contract.id, monthly_rent=-500))

    def test_due_day_zero_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            LeaseCreate(**make_lease(contract_id=contract.id, due_day=0))

    def test_due_day_above_31_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            LeaseCreate(**make_lease(contract_id=contract.id, due_day=32))

    def test_end_date_before_start_date_raises_validation_error(self, db, contract):
        today = date.today()
        with pytest.raises(ValidationError):
            LeaseCreate(**make_lease(contract_id=contract.id, start_date=today, end_date=today - timedelta(days=1)))

    def test_end_date_same_as_start_date_raises_validation_error(self, db, contract):
        today = date.today()
        with pytest.raises(ValidationError):
            LeaseCreate(**make_lease(contract_id=contract.id, start_date=today, end_date=today))

    def test_both_late_fee_fields_set_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            LeaseCreate(**make_lease(contract_id=contract.id, late_fee_amount=500.0, late_fee_percent=5.0))

    def test_neither_late_fee_field_set_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            LeaseCreate(**make_lease(contract_id=contract.id, late_fee_amount=None, late_fee_percent=None))

    def test_grace_period_days_negative_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            LeaseCreate(**make_lease(contract_id=contract.id, grace_period_days=-1))


# ─── update ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLeaseRepositoryUpdate:
    async def test_updates_specified_fields_only(self, db, active_lease):
        payload = LeaseUpdate(monthly_rent=18000.00)
        result = await lease_repo.update(db, active_lease.id, payload)
        assert result.monthly_rent == 18000.00
        assert result.contract_id == active_lease.contract_id

    async def test_returns_none_when_lease_not_found(self, db):
        payload = LeaseUpdate(monthly_rent=18000.00)
        result = await lease_repo.update(db, uuid.uuid4(), payload)
        assert result is None

    async def test_update_status(self, db, active_lease):
        payload = LeaseUpdate(status="ENDED")
        result = await lease_repo.update(db, active_lease.id, payload)
        assert result.status == "ENDED"

    async def test_empty_payload_is_a_no_op(self, db, active_lease):
        payload = LeaseUpdate()
        result = await lease_repo.update(db, active_lease.id, payload)
        assert result.monthly_rent == active_lease.monthly_rent
        assert result.status == active_lease.status


class TestLeaseRepositoryUpdateEdgeCases:
    def test_monthly_rent_zero_raises_validation_error(self, db):
        with pytest.raises(ValidationError):
            LeaseUpdate(monthly_rent=0)

    def test_due_day_above_31_raises_validation_error(self, db):
        with pytest.raises(ValidationError):
            LeaseUpdate(due_day=32)

    def test_both_late_fee_fields_set_raises_validation_error(self, db):
        with pytest.raises(ValidationError):
            LeaseUpdate(late_fee_amount=500.0, late_fee_percent=5.0)


# ─── delete ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLeaseRepositoryDelete:
    async def test_deletes_lease_successfully(self, db, active_lease):
        lease_id = active_lease.id
        delete_result = await lease_repo.delete(db, lease_id)
        assert delete_result is not None
        lease = await lease_repo.get_by_id(db, lease_id)
        assert lease is None

    async def test_returns_none_when_not_found(self, db):
        result = await lease_repo.delete(db, uuid.uuid4())
        assert result is None


# ─── get_all_for_manager / count_all_for_manager ─────────────────────────────


@pytest.mark.asyncio
class TestLeaseRepositoryGetAllForManager:
    async def test_returns_only_leases_for_managers_own_properties(self, db, tenant, manager):
        other_mgr = await make_manager_model(db, username="other_mgr_l", email="other_mgr_l@example.com")
        owned_property = await make_property_model(db, manager_id=manager.id)
        other_property = await make_property_model(db, name="Other Property", manager_id=other_mgr.id)

        owned_contract = await make_contract_model(db, property_id=owned_property.id, tenant_id=tenant.id)
        other_contract = await make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id)

        owned_lease = await make_lease_model(db, contract_id=owned_contract.id)
        await make_lease_model(db, contract_id=other_contract.id)

        result = await lease_repo.get_all_for_manager(db, manager.id)
        assert len(result) == 1
        assert result[0].id == owned_lease.id

    async def test_returns_empty_list_when_manager_owns_no_properties(self, db, contract):
        await make_lease_model(db, contract_id=contract.id)
        result = await lease_repo.get_all_for_manager(db, uuid.uuid4())
        assert result == []

    async def test_count_matches_get_all_for_manager(self, db, tenant, manager):
        owned_property = await make_property_model(db, manager_id=manager.id)
        second_property = await make_property_model(db, name="Second Property", manager_id=manager.id)
        c1 = await make_contract_model(db, property_id=owned_property.id, tenant_id=tenant.id)
        c2 = await make_contract_model(db, property_id=second_property.id, tenant_id=tenant.id)
        await make_lease_model(db, contract_id=c1.id)
        await make_lease_model(db, contract_id=c2.id)

        total = await lease_repo.count_all_for_manager(db, manager.id)
        assert total == 2
