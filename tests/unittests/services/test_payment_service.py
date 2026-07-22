import pytest

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.payment import PaymentCreate, PaymentUpdate
from app.services.payment_service import PaymentService
from app.services.exceptions import (
    PaymentForbiddenError,
    RelatedResourceNotFoundError,
    ResourceForbiddenError,
)
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_admin, make_manager


class MockPaymentRepo(MockCRUDRepo):
    """Adds Payment's own query methods on top of the generic CRUD base."""

    async def get_by_contract(self, db, contract_id):
        return await self._filter_by(contract_id=contract_id)

    async def get_by_status(self, db, status):
        return await self._filter_by(status=status)


class MockPaymentRepoWithScoping(MockPaymentRepo):
    """Adds a fake `get_all_for_manager`/`count_all_for_manager` that
    filters directly off a `manager_id` attribute stashed on each mock
    record, not the real contract/property join. The real join semantics
    are covered by PaymentRepository's own tests against a real DB; this
    only needs to confirm PaymentService.list_payments calls the right
    repo method for the right role."""

    async def get_all_for_manager(self, db, manager_id, skip=0, limit=100):
        return [p for p in self.records.values() if getattr(p, "manager_id", None) == manager_id]


def _make_service(contracts=None, properties=None, payments=None):
    return PaymentService(
        payment_repo=MockPaymentRepo(payments),
        contract_repo=MockReadOnlyRepo(contracts),
        property_repo=MockReadOnlyRepo(properties),
    )


def _payload(**kwargs):
    defaults = dict(
        contract_id=uuid4(),
        amount=Decimal("15000.00"),
        payment_method="cash",
        status="PAID",
    )
    defaults.update(kwargs)
    return PaymentCreate(**defaults)


# ─── Construction / class attributes ───────────────────────────────────────


class TestPaymentServiceClassAttributes:
    def test_forbidden_error_is_payment_forbidden_error(self):
        assert PaymentService.forbidden_error is PaymentForbiddenError

    def test_payment_forbidden_error_is_a_resource_forbidden_error(self):
        assert issubclass(PaymentForbiddenError, ResourceForbiddenError)

    def test_contract_repo_and_property_repo_default_to_none(self):
        svc = PaymentService(payment_repo=MockPaymentRepo())
        assert svc.contract_repo is None
        assert svc.property_repo is None


# ─── get_payment ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetPayment:
    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_payment(mock_db, uuid4(), make_admin())

    async def test_admin_can_access_any_payment(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        payment = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        svc = _make_service(
            payments={payment.id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.get_payment(mock_db, payment.id, make_admin())
        assert result is payment

    async def test_manager_can_access_payment_for_owned_property(self, mock_db):
        manager_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        svc = _make_service(
            payments={payment.id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
        )

        result = await svc.get_payment(mock_db, payment.id, make_manager(manager_id))
        assert result is payment

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        payment = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        svc = _make_service(
            payments={payment.id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(PaymentForbiddenError):
            await svc.get_payment(mock_db, payment.id, make_manager())


# ─── list_payments ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListPayments:
    async def test_current_user_is_required(self, mock_db):
        """current_user has no default — a caller that forgets to pass it
        gets a loud TypeError, not a silent bypass."""
        svc = PaymentService(payment_repo=MockPaymentRepoWithScoping())
        with pytest.raises(TypeError):
            await svc.list_payments(mock_db)

    async def test_admin_sees_all_payments(self, mock_db):
        owned = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        other = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = PaymentService(payment_repo=MockPaymentRepoWithScoping({owned.id: owned, other.id: other}))

        result = await svc.list_payments(mock_db, current_user=make_admin())

        assert result.items == [owned, other]
        assert result.total == 2

    async def test_manager_only_sees_payments_for_own_properties(self, mock_db):
        manager = make_manager()
        owned = SimpleNamespace(id=uuid4(), manager_id=manager.id)
        other = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = PaymentService(payment_repo=MockPaymentRepoWithScoping({owned.id: owned, other.id: other}))

        result = await svc.list_payments(mock_db, current_user=manager)

        assert result.items == [owned]
        assert result.total == 1


# ─── create_payment ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCreatePayment:
    async def test_admin_can_create_for_any_contract(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.create_payment(mock_db, _payload(contract_id=contract_id), current_user=make_admin())

        assert result.contract_id == contract_id
        assert mock_db.commit.called

    async def test_manager_can_create_for_owned_contract(self, mock_db):
        manager_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
        )

        result = await svc.create_payment(
            mock_db, _payload(contract_id=contract_id), current_user=make_manager(manager_id)
        )

        assert result.contract_id == contract_id

    async def test_manager_forbidden_for_unowned_contract(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(PaymentForbiddenError):
            await svc.create_payment(mock_db, _payload(contract_id=contract_id), current_user=make_manager())

        assert repo.created_payloads == []
        assert not mock_db.commit.called

    async def test_raises_when_contract_does_not_exist(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_payment(mock_db, _payload(), current_user=make_admin())

    async def test_skips_authorization_when_no_current_user(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.create_payment(mock_db, _payload(contract_id=contract_id))
        assert result.contract_id == contract_id


# ─── update_payment ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpdatePayment:
    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.update_payment(mock_db, uuid4(), PaymentUpdate(status="REFUNDED"), current_user=make_admin())

    async def test_admin_can_update_any_payment(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status="PAID")
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.update_payment(
            mock_db, payment_id, PaymentUpdate(status="REFUNDED"), current_user=make_admin()
        )
        assert result.status == "REFUNDED"
        assert mock_db.commit.called

    async def test_manager_forbidden_for_unowned_payment(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status="PAID")
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(PaymentForbiddenError):
            await svc.update_payment(mock_db, payment_id, PaymentUpdate(status="REFUNDED"), current_user=make_manager())

        assert repo.updated_payloads == []
        assert not mock_db.commit.called

    async def test_skips_authorization_when_no_current_user(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status="PAID")
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.update_payment(mock_db, payment_id, PaymentUpdate(status="REFUNDED"))
        assert result.status == "REFUNDED"


# ─── delete_payment ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeletePayment:
    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.delete_payment(mock_db, uuid4())

    async def test_admin_can_delete_any_payment(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.delete_payment(mock_db, payment_id, current_user=make_admin())
        assert result is payment
        assert mock_db.commit.called

    async def test_manager_can_delete_owned_payment(self, mock_db):
        manager_id, payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
        )

        result = await svc.delete_payment(mock_db, payment_id, current_user=make_manager(manager_id))
        assert result is payment

    async def test_manager_forbidden_for_unowned_payment(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(PaymentForbiddenError):
            await svc.delete_payment(mock_db, payment_id, current_user=make_manager())

        assert repo.deleted_ids == []
        assert not mock_db.commit.called

    async def test_skips_authorization_when_no_current_user(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.delete_payment(mock_db, payment_id)
        assert result is payment


# ─── Delegated read-only passthroughs ───────────────────────────────────────


@pytest.mark.asyncio
class TestDelegatedRepoPassthroughs:
    async def test_get_by_contract(self, mock_db):
        contract_id = uuid4()
        payment = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        svc = _make_service(payments={payment.id: payment})
        assert await svc.get_by_contract(mock_db, contract_id) == [payment]

    async def test_get_by_status(self, mock_db):
        payment = SimpleNamespace(id=uuid4(), status="PENDING")
        svc = _make_service(payments={payment.id: payment})
        assert await svc.get_by_status(mock_db, "PENDING") == [payment]
