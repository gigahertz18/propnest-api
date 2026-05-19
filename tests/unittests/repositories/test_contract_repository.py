import pytest
import uuid
from datetime import date, timedelta

from pydantic import ValidationError

from app.repositories.contract import contract_repo
from app.schemas.contract import ContractCreate, ContractUpdate
from app.models.contract import RentalType
from tests.factories import make_contract, make_contract_model, make_property_model, make_tenant_model


# ─── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def property_(db):
    """A persisted Property for FK references."""
    return make_property_model(db)


@pytest.fixture
def tenant(db):
    """A persisted Tenant for FK references."""
    return make_tenant_model(db)


@pytest.fixture
def active_contract(db, property_, tenant):
    """A single ACTIVE contract ready to use in tests."""
    return make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)


# ─── get_all ──────────────────────────────────────────────────────────────────

class TestContractRepositoryGetAll:
    def test_returns_empty_list_when_no_contracts(self, db):
        result = contract_repo.get_all(db)
        assert result == []

    def test_returns_all_contracts(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        result = contract_repo.get_all(db)
        assert len(result) == 2

    def test_skip_and_limit(self, db, property_, tenant):
        # Create contracts across multiple properties to avoid DB-level
        # uniqueness conflicts on active contracts.
        for i in range(5):
            p = make_property_model(db, name=f"Property {i}")
            make_contract_model(db, property_id=p.id, tenant_id=tenant.id)
        result = contract_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_limit_zero_returns_empty_list(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        result = contract_repo.get_all(db, limit=0)
        assert result == []

    def test_skip_beyond_total_returns_empty_list(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        result = contract_repo.get_all(db, skip=999)
        assert result == []


# ─── get_by_id ────────────────────────────────────────────────────────────────

class TestContractRepositoryGetById:
    def test_returns_contract_when_found(self, db, active_contract):
        result = contract_repo.get_by_id(db, active_contract.id)
        assert result is not None
        assert result.id == active_contract.id

    def test_returns_none_when_not_found(self, db):
        result = contract_repo.get_by_id(db, uuid.uuid4())
        assert result is None


# ─── create ───────────────────────────────────────────────────────────────────

class TestContractRepositoryCreate:
    def test_creates_contract_successfully(self, db, property_, tenant):
        payload = ContractCreate(**make_contract(
            property_id=property_.id,
            tenant_id=tenant.id,
        ))
        result = contract_repo.create(db, payload)
        assert result.id is not None
        assert result.property_id == property_.id
        assert result.tenant_id == tenant.id
        assert result.rental_type == RentalType.long_term
        assert result.rent_amount == 15000.00
        assert result.status == "ACTIVE"

    def test_created_contract_is_persisted(self, db, property_, tenant):
        payload = ContractCreate(**make_contract(
            property_id=property_.id,
            tenant_id=tenant.id,
            rent_amount=20000.00,
        ))
        created = contract_repo.create(db, payload)
        fetched = contract_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.rent_amount == 20000.00

    def test_default_status_is_active(self, db, property_, tenant):
        payload = ContractCreate(**make_contract(
            property_id=property_.id,
            tenant_id=tenant.id,
        ))
        result = contract_repo.create(db, payload)
        assert result.status == "ACTIVE"

    def test_default_booking_source_is_direct(self, db, property_, tenant):
        payload = ContractCreate(**make_contract(
            property_id=property_.id,
            tenant_id=tenant.id,
        ))
        result = contract_repo.create(db, payload)
        assert result.booking_source == "direct"

    def test_end_date_is_optional(self, db, property_, tenant):
        payload = ContractCreate(**make_contract(
            property_id=property_.id,
            tenant_id=tenant.id,
            end_date=None,
        ))
        result = contract_repo.create(db, payload)
        assert result.end_date is None

    def test_deposit_is_optional(self, db, property_, tenant):
        payload = ContractCreate(**make_contract(
            property_id=property_.id,
            tenant_id=tenant.id,
            deposit=None,
        ))
        result = contract_repo.create(db, payload)
        assert result.deposit is None

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_rent_amount_zero_raises_validation_error(self, db, property_, tenant):
        with pytest.raises(ValidationError):
            ContractCreate(**make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
                rent_amount=0,
            ))

    def test_rent_amount_negative_raises_validation_error(self, db, property_, tenant):
        with pytest.raises(ValidationError):
            ContractCreate(**make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
                rent_amount=-500,
            ))

    def test_end_date_same_as_start_date_raises_validation_error(self, db, property_, tenant):
        today = date.today()
        with pytest.raises(ValidationError):
            ContractCreate(**make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
                start_date=today,
                end_date=today,
            ))

    def test_end_date_before_start_date_raises_validation_error(self, db, property_, tenant):
        today = date.today()
        with pytest.raises(ValidationError):
            ContractCreate(**make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
                start_date=today,
                end_date=today - timedelta(days=1),
            ))

    def test_invalid_booking_source_raises_validation_error(self, db, property_, tenant):
        with pytest.raises(ValidationError):
            ContractCreate(**make_contract(
                property_id=property_.id,
                tenant_id=tenant.id,
                booking_source="invalid_platform",
            ))


# ─── update ───────────────────────────────────────────────────────────────────

class TestContractRepositoryUpdate:
    def test_updates_specified_fields_only(self, db, active_contract):
        payload = ContractUpdate(rent_amount=18000.00)
        result = contract_repo.update(db, active_contract.id, payload)
        assert result.rent_amount == 18000.00
        assert result.property_id == active_contract.property_id
        assert result.tenant_id == active_contract.tenant_id

    def test_returns_none_when_contract_not_found(self, db):
        payload = ContractUpdate(rent_amount=18000.00)
        result = contract_repo.update(db, uuid.uuid4(), payload)
        assert result is None

    def test_update_status(self, db, active_contract):
        payload = ContractUpdate(status="EXPIRED")
        result = contract_repo.update(db, active_contract.id, payload)
        assert result.status == "EXPIRED"

    def test_update_end_date(self, db, active_contract):
        new_end = date.today() + timedelta(days=180)
        payload = ContractUpdate(end_date=new_end)
        result = contract_repo.update(db, active_contract.id, payload)
        assert result.end_date == new_end

    def test_update_booking_source(self, db, active_contract):
        payload = ContractUpdate(booking_source="airbnb")
        result = contract_repo.update(db, active_contract.id, payload)
        assert result.booking_source == "airbnb"

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_empty_payload_is_a_no_op(self, db, active_contract):
        """Sending no fields should leave the contract unchanged."""
        payload = ContractUpdate()
        result = contract_repo.update(db, active_contract.id, payload)
        assert result.rent_amount == active_contract.rent_amount
        assert result.status == active_contract.status
        assert result.booking_source == active_contract.booking_source

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

class TestContractRepositoryDelete:
    def test_deletes_contract_successfully(self, db, active_contract):
        contract_id = active_contract.id
        result = contract_repo.delete(db, contract_id)
        assert result is not None
        assert contract_repo.get_by_id(db, contract_id) is None

    def test_returns_none_when_not_found(self, db):
        result = contract_repo.delete(db, uuid.uuid4())
        assert result is None


# ─── get_by_property ──────────────────────────────────────────────────────────

class TestContractRepositoryGetByProperty:
    def test_returns_contracts_for_property(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        other_property = make_property_model(db, name="Other Property")
        make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id)

        result = contract_repo.get_by_property(db, property_.id)
        assert len(result) == 2
        assert all(c.property_id == property_.id for c in result)

    def test_returns_empty_list_when_no_contracts_for_property(self, db, property_):
        result = contract_repo.get_by_property(db, property_.id)
        assert result == []

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_returns_empty_list_for_nonexistent_property_id(self, db):
        """A UUID that was never inserted should return an empty list, not raise."""
        result = contract_repo.get_by_property(db, uuid.uuid4())
        assert result == []


# ─── get_by_tenant ────────────────────────────────────────────────────────────

class TestContractRepositoryGetByTenant:
    def test_returns_contracts_for_tenant(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        other_tenant = make_tenant_model(db, email="other@example.com")
        other_property = make_property_model(db, name="Other Property")
        make_contract_model(db, property_id=other_property.id, tenant_id=other_tenant.id)

        result = contract_repo.get_by_tenant(db, tenant.id)
        assert len(result) == 2
        assert all(c.tenant_id == tenant.id for c in result)

    def test_returns_empty_list_when_no_contracts_for_tenant(self, db, tenant):
        result = contract_repo.get_by_tenant(db, tenant.id)
        assert result == []

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_returns_empty_list_for_nonexistent_tenant_id(self, db):
        """A UUID that was never inserted should return an empty list, not raise."""
        result = contract_repo.get_by_tenant(db, uuid.uuid4())
        assert result == []


# ─── get_by_status ────────────────────────────────────────────────────────────

class TestContractRepositoryGetByStatus:
    def test_returns_contracts_with_matching_status(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="ACTIVE")
        other_property = make_property_model(db, name="Other Property")
        make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id, status="ACTIVE")
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")

        result = contract_repo.get_by_status(db, "ACTIVE")
        assert len(result) == 2
        assert all(c.status == "ACTIVE" for c in result)

    def test_returns_empty_list_when_no_matching_status(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="ACTIVE")
        result = contract_repo.get_by_status(db, "TERMINATED")
        assert result == []


# ─── get_by_rental_type ───────────────────────────────────────────────────────

class TestContractRepositoryGetByRentalType:
    def test_returns_contracts_with_matching_rental_type(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, rental_type=RentalType.long_term)
        other_property = make_property_model(db, name="Other Property")
        make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id, rental_type=RentalType.long_term)
        # Place the non-matching short-term contract on a different property
        third_property = make_property_model(db, name="Third Property")
        make_contract_model(db, property_id=third_property.id, tenant_id=tenant.id, rental_type=RentalType.short_term)

        result = contract_repo.get_by_rental_type(db, RentalType.long_term)
        assert len(result) == 2
        assert all(c.rental_type == RentalType.long_term for c in result)

    def test_returns_empty_list_when_no_matching_rental_type(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, rental_type=RentalType.long_term)
        result = contract_repo.get_by_rental_type(db, RentalType.short_term)
        assert result == []


# ─── get_by_booking_source ────────────────────────────────────────────────────

class TestContractRepositoryGetByBookingSource:
    def test_returns_contracts_with_matching_booking_source(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, booking_source="airbnb")
        other_property = make_property_model(db, name="Other Property")
        make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id, booking_source="airbnb")
        # Ensure the non-matching direct booking is on a different property
        third_property = make_property_model(db, name="Third Property")
        make_contract_model(db, property_id=third_property.id, tenant_id=tenant.id, booking_source="direct")

        result = contract_repo.get_by_booking_source(db, "airbnb")
        assert len(result) == 2
        assert all(c.booking_source == "airbnb" for c in result)

    def test_returns_empty_list_when_no_matching_booking_source(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, booking_source="direct")
        result = contract_repo.get_by_booking_source(db, "agoda")
        assert result == []


# ─── get_active_contract_by_property ─────────────────────────────────────────

class TestContractRepositoryGetActiveContractByProperty:
    def test_returns_active_contract_for_property(self, db, property_, tenant):
        contract = make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="ACTIVE")
        result = contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is not None
        assert result.id == contract.id

    def test_returns_none_when_no_active_contract(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        result = contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is None

    def test_returns_none_when_property_has_no_contracts(self, db, property_):
        result = contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is None

    def test_ignores_non_active_contracts(self, db, property_, tenant):
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="TERMINATED")
        result = contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is None

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_returns_correct_active_contract_among_mixed_statuses(self, db, property_, tenant):
        """Property has EXPIRED, TERMINATED, and ACTIVE — only ACTIVE is returned."""
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")
        make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="TERMINATED")
        active = make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="ACTIVE")

        result = contract_repo.get_active_contract_by_property(db, property_.id)
        assert result is not None
        assert result.id == active.id

    def test_returns_none_for_nonexistent_property_id(self, db):
        """A UUID that was never inserted should return None, not raise."""
        result = contract_repo.get_active_contract_by_property(db, uuid.uuid4())
        assert result is None
