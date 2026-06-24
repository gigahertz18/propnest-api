import pytest
import pytest_asyncio
import uuid
from datetime import date, timedelta

from pydantic import ValidationError

from app.repositories.contract import contract_repo
from app.schemas.contract import ContractCreate, ContractUpdate
from app.models.contract import RentalType
from tests.factories import make_contract, make_contract_model, make_property_model, make_tenant_model

# ─── Shared fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def property_(db):
    """A persisted Property for FK references."""
    return await make_property_model(db)


@pytest_asyncio.fixture
async def tenant(db):
    """A persisted Tenant for FK references."""
    return await make_tenant_model(db)


@pytest_asyncio.fixture
async def active_contract(db, property_, tenant):
    """A single ACTIVE contract ready to use in tests."""
    return await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)


# ─── get_all ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryGetAll:
    async def test_returns_empty_list_when_no_contracts(self, db):
        result = await contract_repo.get_all(db)
        assert result == []

    async def test_returns_all_contracts(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        result = await contract_repo.get_all(db)
        assert len(result) == 2

    async def test_skip_and_limit(self, db, property_, tenant):
        # Create contracts across multiple properties to avoid DB-level
        # uniqueness conflicts on active contracts.
        for i in range(5):
            p = await make_property_model(db, name=f"Property {i}")
            await make_contract_model(db, property_id=p.id, tenant_id=tenant.id)
        result = await contract_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2

    # ── Edge cases ────────────────────────────────────────────────────────────

    async def test_limit_zero_returns_empty_list(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        result = await contract_repo.get_all(db, limit=0)
        assert result == []

    async def test_skip_beyond_total_returns_empty_list(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        result = await contract_repo.get_all(db, skip=999)
        assert result == []


# ─── get_by_id ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryGetById:
    async def test_returns_contract_when_found(self, db, active_contract):
        result = await contract_repo.get_by_id(db, active_contract.id)
        assert result is not None
        assert result.id == active_contract.id

    async def test_returns_none_when_not_found(self, db):
        result = await contract_repo.get_by_id(db, uuid.uuid4())
        assert result is None


# ─── create ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryCreate:
    async def test_creates_contract_successfully(self, db, property_, tenant):
        payload = ContractCreate(
            **make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
            )
        )
        result = await contract_repo.create(db, payload)
        assert result.id is not None
        assert result.property_id == property_.id
        assert result.tenant_id == tenant.id
        assert result.rental_type == RentalType.long_term
        assert result.rent_amount == 15000.00
        assert result.status == "ACTIVE"

    async def test_created_contract_is_persisted(self, db, property_, tenant):
        payload = ContractCreate(
            **make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
                rent_amount=20000.00,
            )
        )
        created = await contract_repo.create(db, payload)
        fetched = await contract_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.rent_amount == 20000.00

    async def test_default_status_is_active(self, db, property_, tenant):
        payload = ContractCreate(
            **make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
            )
        )
        result = await contract_repo.create(db, payload)
        assert result.status == "ACTIVE"

    async def test_default_booking_source_is_direct(self, db, property_, tenant):
        payload = ContractCreate(
            **make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
            )
        )
        result = await contract_repo.create(db, payload)
        assert result.booking_source == "direct"

    async def test_end_date_is_optional(self, db, property_, tenant):
        payload = ContractCreate(
            **make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
                end_date=None,
            )
        )
        result = await contract_repo.create(db, payload)
        assert result.end_date is None

    async def test_deposit_is_optional(self, db, property_, tenant):
        payload = ContractCreate(
            **make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
                deposit=None,
            )
        )
        result = await contract_repo.create(db, payload)
        assert result.deposit is None

class TestContractRepositoryCreateEdgeCases:
    def test_rent_amount_zero_raises_validation_error(self, db, property_, tenant):
        with pytest.raises(ValidationError):
            ContractCreate(
                **make_contract(
                    property_id=property_.id,
                    tenant_id=tenant.id,
                    rent_amount=0,
                )
            )

    def test_rent_amount_negative_raises_validation_error(self, db, property_, tenant):
        with pytest.raises(ValidationError):
            ContractCreate(
                **make_contract(
                    property_id=property_.id,
                    tenant_id=tenant.id,
                    rent_amount=-500,
                )
            )

    def test_end_date_same_as_start_date_raises_validation_error(self, db, property_, tenant):
        today = date.today()
        with pytest.raises(ValidationError):
            ContractCreate(
                **make_contract(
                    property_id=property_.id,
                    tenant_id=tenant.id,
                    start_date=today,
                    end_date=today,
                )
            )

    def test_end_date_before_start_date_raises_validation_error(self, db, property_, tenant):
        today = date.today()
        with pytest.raises(ValidationError):
            ContractCreate(
                **make_contract(
                    property_id=property_.id,
                    tenant_id=tenant.id,
                    start_date=today,
                    end_date=today - timedelta(days=1),
                )
            )

    def test_invalid_booking_source_raises_validation_error(self, db, property_, tenant):
        with pytest.raises(ValidationError):
            ContractCreate(
                **make_contract(
                    property_id=property_.id,
                    tenant_id=tenant.id,
                    booking_source="invalid_platform",
                )
            )

# ─── update ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryUpdate:
    async def test_updates_specified_fields_only(self, db, active_contract):
        payload = ContractUpdate(rent_amount=18000.00)
        result = await contract_repo.update(db, active_contract.id, payload)
        assert result.rent_amount == 18000.00
        assert result.property_id == active_contract.property_id
        assert result.tenant_id == active_contract.tenant_id

    async def test_returns_none_when_contract_not_found(self, db):
        payload = ContractUpdate(rent_amount=18000.00)
        result = await contract_repo.update(db, uuid.uuid4(), payload)
        assert result is None

    async def test_update_status(self, db, active_contract):
        payload = ContractUpdate(status="EXPIRED")
        result = await contract_repo.update(db, active_contract.id, payload)
        assert result.status == "EXPIRED"

    async def test_update_end_date(self, db, active_contract):
        new_end = date.today() + timedelta(days=180)
        payload = ContractUpdate(end_date=new_end)
        result = await contract_repo.update(db, active_contract.id, payload)
        assert result.end_date == new_end

    async def test_update_booking_source(self, db, active_contract):
        payload = ContractUpdate(booking_source="airbnb")
        result = await contract_repo.update(db, active_contract.id, payload)
        assert result.booking_source == "airbnb"

    async def test_empty_payload_is_a_no_op(self, db, active_contract):
        """Sending no fields should leave the contract unchanged."""
        payload = ContractUpdate()
        result = await contract_repo.update(db, active_contract.id, payload)
        assert result.rent_amount == active_contract.rent_amount
        assert result.status == active_contract.status
        assert result.booking_source == active_contract.booking_source

class TestContractRespositoryUpdateEdgeCases:
    def test_rent_amount_zero_raises_validation_error(self, db):
        with pytest.raises(ValidationError):
            ContractUpdate(rent_amount=0)

    def test_rent_amount_negative_raises_validation_error(self, db):
        with pytest.raises(ValidationError):
            ContractUpdate(rent_amount=-1)

    def test_end_date_before_start_date_raises_validation_error(self, db):
        with pytest.raises(ValidationError):
            ContractUpdate(
                start_date=date.today(),
                end_date=date.today() - timedelta(days=1),
            )

    def test_end_date_same_as_start_date_raises_validation_error(self, db):
        today = date.today()
        with pytest.raises(ValidationError):
            ContractUpdate(start_date=today, end_date=today)

    def test_invalid_booking_source_raises_validation_error(self, db):
        with pytest.raises(ValidationError):
            ContractUpdate(booking_source="invalid_platform")


# ─── delete ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryDelete:
    async def test_deletes_contract_successfully(self, db, active_contract):
        contract_id = active_contract.id
        delete_result = await contract_repo.delete(db, contract_id)
        assert delete_result is not None
        contract = await contract_repo.get_by_id(db, contract_id)
        assert contract is None

    async def test_returns_none_when_not_found(self, db):
        result = await contract_repo.delete(db, uuid.uuid4())
        assert result is None


# ─── get_by_property ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryGetByProperty:
    async def test_returns_contracts_for_property(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        other_property = await make_property_model(db, name="Other Property")
        await make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id)

        result = await contract_repo.get_by_property(db, property_.id)
        assert len(result) == 2
        assert all(c.property_id == property_.id for c in result)

    async def test_returns_empty_list_when_no_contracts_for_property(self, db, property_):
        result = await contract_repo.get_by_property(db, property_.id)
        assert result == []

    # ── Edge cases ────────────────────────────────────────────────────────────

    async def test_returns_empty_list_for_nonexistent_property_id(self, db):
        """A UUID that was never inserted should return an empty list, not raise."""
        result = await contract_repo.get_by_property(db, uuid.uuid4())
        assert result == []


# ─── get_by_tenant ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryGetByTenant:
    async def test_returns_contracts_for_tenant(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        other_tenant = await make_tenant_model(db, email="other@example.com")
        other_property = await make_property_model(db, name="Other Property")
        await make_contract_model(db, property_id=other_property.id, tenant_id=other_tenant.id)

        result = await contract_repo.get_by_tenant(db, tenant.id)
        assert len(result) == 2
        assert all(c.tenant_id == tenant.id for c in result)

    async def test_returns_empty_list_when_no_contracts_for_tenant(self, db, tenant):
        result = await contract_repo.get_by_tenant(db, tenant.id)
        assert result == []

    # ── Edge cases ────────────────────────────────────────────────────────────

    async def test_returns_empty_list_for_nonexistent_tenant_id(self, db):
        """A UUID that was never inserted should return an empty list, not raise."""
        result = await contract_repo.get_by_tenant(db, uuid.uuid4())
        assert result == []


# ─── get_by_status ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryGetByStatus:
    async def test_returns_contracts_with_matching_status(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="ACTIVE")
        other_property = await make_property_model(db, name="Other Property")
        await make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id, status="ACTIVE")
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")

        result = await contract_repo.get_by_status(db, "ACTIVE")
        assert len(result) == 2
        assert all(c.status == "ACTIVE" for c in result)

    async def test_returns_empty_list_when_no_matching_status(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="ACTIVE")
        result = await contract_repo.get_by_status(db, "TERMINATED")
        assert result == []


# ─── get_by_rental_type ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryGetByRentalType:
    async def test_returns_contracts_with_matching_rental_type(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, rental_type=RentalType.long_term)
        other_property = await make_property_model(db, name="Other Property")
        await make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id, rental_type=RentalType.long_term)
        # Place the non-matching short-term contract on a different property
        third_property = await make_property_model(db, name="Third Property")
        await make_contract_model(db, property_id=third_property.id, tenant_id=tenant.id, rental_type=RentalType.short_term)

        result = await contract_repo.get_by_rental_type(db, RentalType.long_term)
        assert len(result) == 2
        assert all(c.rental_type == RentalType.long_term for c in result)

    async def test_returns_empty_list_when_no_matching_rental_type(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, rental_type=RentalType.long_term)
        result = await contract_repo.get_by_rental_type(db, RentalType.short_term)
        assert result == []


# ─── get_by_booking_source ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryGetByBookingSource:
    async def test_returns_contracts_with_matching_booking_source(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, booking_source="airbnb")
        other_property = await make_property_model(db, name="Other Property")
        await make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id, booking_source="airbnb")
        # Ensure the non-matching direct booking is on a different property
        third_property = await make_property_model(db, name="Third Property")
        await make_contract_model(db, property_id=third_property.id, tenant_id=tenant.id, booking_source="direct")

        result = await contract_repo.get_by_booking_source(db, "airbnb")
        assert len(result) == 2
        assert all(c.booking_source == "airbnb" for c in result)

    async def test_returns_empty_list_when_no_matching_booking_source(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, booking_source="direct")
        result = await contract_repo.get_by_booking_source(db, "agoda")
        assert result == []


# ─── get_active_contract_by_property ─────────────────────────────────────────

@pytest.mark.asyncio
class TestContractRepositoryGetActiveContractByProperty:
    async def test_returns_active_contract_for_property(self, db, property_, tenant):
        contract = await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="ACTIVE")
        result = await contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is not None
        assert result.id == contract.id

    async def test_returns_none_when_no_active_contract(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        result = await contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is None

    async def test_returns_none_when_property_has_no_contracts(self, db, property_):
        result = await contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is None

    async def test_ignores_non_active_contracts(self, db, property_, tenant):
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="TERMINATED")
        result = await contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is None

    # ── Edge cases ────────────────────────────────────────────────────────────

    async def test_returns_correct_active_contract_among_mixed_statuses(self, db, property_, tenant):
        """Property has EXPIRED, TERMINATED, and ACTIVE — only ACTIVE is returned."""
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="TERMINATED")
        active = await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="ACTIVE")

        result = await contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is not None
        assert result.id == active.id

    async def test_returns_none_for_nonexistent_property_id(self, db):
        """A UUID that was never inserted should return None, not raise."""
        result = await contract_repo.get_active_contract_by_property(db, uuid.uuid4())
        assert result is None
