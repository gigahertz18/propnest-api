import pytest
import pytest_asyncio
import uuid
from decimal import Decimal

from pydantic import ValidationError

from app.repositories.payment import payment_repo
from app.schemas.payment import PaymentCreate, PaymentUpdate
from tests.factories import (
    make_payment,
    make_payment_model,
    make_property_model,
    make_tenant_model,
    make_contract_model,
    make_manager_model,
)

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
async def manager(db):
    """A persisted Manager for FK references."""
    return await make_manager_model(db)


@pytest_asyncio.fixture
async def contract(db, property_, tenant):
    """A persisted Contract for FK references."""
    return await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)


@pytest_asyncio.fixture
async def payment(db, contract):
    """A single payment ready to use in tests."""
    return await make_payment_model(db, contract.id)


# ─── get_all ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPaymentRepositoryGetAll:
    async def test_returns_empty_list_when_no_payments(self, db):
        result = await payment_repo.get_all(db)
        assert result == []

    async def test_returns_all_payments(self, db, contract):
        await make_payment_model(db, contract.id)
        await make_payment_model(db, contract.id, status="PENDING")
        result = await payment_repo.get_all(db)
        assert len(result) == 2

    async def test_skip_and_limit(self, db, contract):
        for i in range(5):
            await make_payment_model(db, contract.id, amount=1000.00 + i)
        result = await payment_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2

    # ── Edge cases ────────────────────────────────────────────────────────────

    async def test_limit_zero_returns_empty_list(self, db, contract):
        await make_payment_model(db, contract.id)
        result = await payment_repo.get_all(db, limit=0)
        assert result == []

    async def test_skip_beyond_total_returns_empty_list(self, db, contract):
        await make_payment_model(db, contract.id)
        result = await payment_repo.get_all(db, skip=999)
        assert result == []

    async def test_negative_skip_is_clamped_to_zero(self, db, contract):
        await make_payment_model(db, contract.id)
        await make_payment_model(db, contract.id)
        result = await payment_repo.get_all(db, skip=-5)
        assert len(result) == 2


# ─── get_by_id ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPaymentRepositoryGetById:
    async def test_returns_payment_when_found(self, db, payment):
        result = await payment_repo.get_by_id(db, payment.id)
        assert result is not None
        assert result.id == payment.id

    async def test_returns_none_when_not_found(self, db):
        result = await payment_repo.get_by_id(db, uuid.uuid4())
        assert result is None


# ─── create ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPaymentRepositoryCreate:
    async def test_creates_payment_successfully(self, db, contract):
        payload = PaymentCreate(**make_payment(contract_id=contract.id))
        result = await payment_repo.create(db, payload)
        assert result.id is not None
        assert result.contract_id == contract.id
        assert result.amount == Decimal("15000.00")
        assert result.status == "PAID"

    async def test_created_payment_is_persisted(self, db, contract):
        payload = PaymentCreate(**make_payment(contract_id=contract.id, amount=2500.00))
        created = await payment_repo.create(db, payload)
        fetched = await payment_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.amount == Decimal("2500.00")

    async def test_default_status_is_paid(self, db, contract):
        payload = PaymentCreate(**make_payment(contract_id=contract.id))
        result = await payment_repo.create(db, payload)
        assert result.status == "PAID"

    async def test_payment_method_is_optional(self, db, contract):
        payload = PaymentCreate(**make_payment(contract_id=contract.id, payment_method=None))
        result = await payment_repo.create(db, payload)
        assert result.payment_method is None


class TestPaymentRepositoryCreateEdgeCases:
    def test_amount_zero_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            PaymentCreate(**make_payment(contract_id=contract.id, amount=0))

    def test_amount_negative_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            PaymentCreate(**make_payment(contract_id=contract.id, amount=-500))

    def test_invalid_payment_method_raises_validation_error(self, db, contract):
        with pytest.raises(ValidationError):
            PaymentCreate(**make_payment(contract_id=contract.id, payment_method="bitcoin"))


# ─── update ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPaymentRepositoryUpdate:
    async def test_updates_status(self, db, payment):
        result = await payment_repo.update(db, payment.id, PaymentUpdate(status="REFUNDED"))
        assert result is not None
        assert result.status == "REFUNDED"

    async def test_updates_amount(self, db, payment):
        result = await payment_repo.update(db, payment.id, PaymentUpdate(amount=Decimal("999.99")))
        assert result is not None
        assert result.amount == Decimal("999.99")

    async def test_returns_none_when_not_found(self, db):
        result = await payment_repo.update(db, uuid.uuid4(), PaymentUpdate(status="REFUNDED"))
        assert result is None


# ── Edge cases ────────────────────────────────────────────────────────────
class TestPaymentRepositoryUpdateEdgeCases:
    def test_invalid_payment_method_raises_validation_error(self):
        with pytest.raises(ValidationError):
            PaymentUpdate(payment_method="bitcoin")

    def test_non_positive_amount_raises_validation_error(self):
        with pytest.raises(ValidationError):
            PaymentUpdate(amount=0)


# ─── delete ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPaymentRepositoryDelete:
    async def test_deletes_payment_successfully(self, db, payment):
        payment_id = payment.id
        delete_result = await payment_repo.delete(db, payment_id)
        assert delete_result is not None
        result = await payment_repo.get_by_id(db, payment_id)
        assert result is None

    async def test_returns_none_when_not_found(self, db):
        result = await payment_repo.delete(db, uuid.uuid4())
        assert result is None


# ─── get_by_contract ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPaymentRepositoryGetByContract:
    async def test_returns_payments_for_contract(self, db, contract):
        await make_payment_model(db, contract.id)
        await make_payment_model(db, contract.id, status="PENDING")

        other_property = await make_property_model(db, name="Other Property")
        other_tenant = await make_tenant_model(db, email="other-tenant@example.com")
        other_contract = await make_contract_model(db, property_id=other_property.id, tenant_id=other_tenant.id)
        await make_payment_model(db, other_contract.id)

        result = await payment_repo.get_by_contract(db, contract.id)
        assert len(result) == 2
        assert all(p.contract_id == contract.id for p in result)

    async def test_returns_empty_list_when_no_payments_for_contract(self, db, contract):
        result = await payment_repo.get_by_contract(db, contract.id)
        assert result == []

    # ── Edge cases ────────────────────────────────────────────────────────────

    async def test_returns_empty_list_for_nonexistent_contract_id(self, db):
        result = await payment_repo.get_by_contract(db, uuid.uuid4())
        assert result == []


# ─── get_by_status ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPaymentRepositoryGetByStatus:
    async def test_returns_payments_with_matching_status(self, db, contract):
        await make_payment_model(db, contract.id, status="PAID")
        await make_payment_model(db, contract.id, status="PAID")
        await make_payment_model(db, contract.id, status="PENDING")

        result = await payment_repo.get_by_status(db, "PAID")
        assert len(result) == 2
        assert all(p.status == "PAID" for p in result)

    async def test_returns_empty_list_when_no_matching_status(self, db, contract):
        await make_payment_model(db, contract.id, status="PAID")
        result = await payment_repo.get_by_status(db, "REFUNDED")
        assert result == []


# ─── get_all_for_manager / count_all_for_manager ─────────────────────────────


@pytest.mark.asyncio
class TestPaymentRepositoryGetAllForManager:
    async def test_returns_only_payments_for_managers_own_properties(self, db, tenant, manager):
        other_mgr = await make_manager_model(db, username="other_mgr", email="other_mgr@example.com")
        owned_property = await make_property_model(db, manager_id=manager.id)
        other_property = await make_property_model(db, name="Other Property", manager_id=other_mgr.id)

        owned_contract = await make_contract_model(db, property_id=owned_property.id, tenant_id=tenant.id)
        other_contract = await make_contract_model(db, property_id=other_property.id, tenant_id=tenant.id)

        owned_payment = await make_payment_model(db, owned_contract.id)
        await make_payment_model(db, other_contract.id)

        result = await payment_repo.get_all_for_manager(db, manager.id)
        assert len(result) == 1
        assert result[0].id == owned_payment.id

    async def test_returns_empty_list_when_manager_owns_no_properties(self, db, contract):
        await make_payment_model(db, contract.id)
        result = await payment_repo.get_all_for_manager(db, uuid.uuid4())
        assert result == []

    async def test_count_matches_get_all_for_manager(self, db, tenant, manager):
        owned_property = await make_property_model(db, manager_id=manager.id)
        owned_contract = await make_contract_model(db, property_id=owned_property.id, tenant_id=tenant.id)
        await make_payment_model(db, owned_contract.id)
        await make_payment_model(db, owned_contract.id)

        total = await payment_repo.count_all_for_manager(db, manager.id)
        assert total == 2
