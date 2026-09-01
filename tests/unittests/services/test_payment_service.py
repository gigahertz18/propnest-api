import pytest


from decimal import Decimal
from pydantic import ValidationError
from types import SimpleNamespace
from uuid import uuid4

from app.core.models.audit_log import AuditAction, AuditLog
from app.models.billing_record import BillingRecordStatus
from app.models.payment import PaymentStatus
from app.schemas.payment import PaymentCreate, PaymentCorrectionCreate, PaymentUpdate
from app.services.lease_billing_service import LeaseBillingService
from app.services.payment_service import PaymentService
from app.core.services.exceptions import (
    PaymentAlreadyVoidedError,
    PaymentForbiddenError,
    RelatedResourceNotFoundError,
    ResourceForbiddenError,
)
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_admin, make_manager, make_regular_user


class MockPaymentRepo(MockCRUDRepo):
    """Adds Payment's own query methods on top of the generic CRUD base."""

    async def get_by_contract(self, db, contract_id):
        return await self._filter_by(contract_id=contract_id)

    async def get_by_status(self, db, status):
        return await self._filter_by(status=status)

    async def get_by_billing_record(self, db, billing_record_id):
        return await self._filter_by(billing_record_id=billing_record_id)


class MockPaymentRepoWithScoping(MockPaymentRepo):
    """Adds a fake `get_all_for_manager`/`count_all_for_manager` that
    filters directly off a `manager_id` attribute stashed on each mock
    record, not the real contract/property join. The real join semantics
    are covered by PaymentRepository's own tests against a real DB; this
    only needs to confirm PaymentService.list_payments calls the right
    repo method for the right role."""

    async def get_all_for_manager(self, db, manager_id, skip=0, limit=100):
        return [p for p in self.records.values() if getattr(p, "manager_id", None) == manager_id]


def _make_service(
    payments=None,
    properties=None,
    contracts=None,
    billing_records=None,
    leases=None,
    lease_billing_service=None,
) -> PaymentService:
    if payments is None:
        payment_repo = MockPaymentRepo({})
    elif isinstance(payments, dict):
        payment_repo = MockPaymentRepo(payments)
    else:
        payment_repo = payments

    if properties is None:
        property_repo = MockReadOnlyRepo({})
    elif isinstance(properties, dict):
        property_repo = MockReadOnlyRepo(properties)
    else:
        property_repo = properties

    if contracts is None:
        contracts_repo = MockReadOnlyRepo({})
    elif isinstance(contracts, dict):
        contracts_repo = MockReadOnlyRepo(contracts)
    else:
        contracts_repo = contracts

    billing_record_repo = (
        billing_records
        if not isinstance(billing_records, (dict, type(None)))
        else MockReadOnlyRepo(billing_records or {})
    )

    lease_repo = leases if not isinstance(leases, (dict, type(None))) else MockReadOnlyRepo(leases or {})

    return PaymentService(
        payment_repo=payment_repo,
        property_repo=property_repo,
        contract_repo=contracts_repo,
        billing_record_repo=billing_record_repo,
        lease_repo=lease_repo,
        lease_billing_service=lease_billing_service or LeaseBillingService(billing_record_repo=None, lease_repo=None),
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

    async def test_user_role_is_forbidden(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        payment = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        svc = _make_service(
            payments={payment.id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(PaymentForbiddenError):
            await svc.get_payment(mock_db, payment.id, make_regular_user())


# ─── list_payments ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListPayments:
    async def test_current_user_is_required(self, mock_db):
        """current_user has no default — a caller that forgets to pass it
        gets a loud TypeError, not a silent bypass."""
        svc = _make_service(payments=MockPaymentRepoWithScoping())
        with pytest.raises(TypeError):
            await svc.list_payments(mock_db)

    async def test_admin_sees_all_payments(self, mock_db):
        owned = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        other = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = _make_service(payments=MockPaymentRepoWithScoping({owned.id: owned, other.id: other}))

        result = await svc.list_payments(mock_db, current_user=make_admin())

        assert result.items == [owned, other]
        assert result.total == 2

    async def test_manager_only_sees_payments_for_own_properties(self, mock_db):
        manager = make_manager()
        owned = SimpleNamespace(id=uuid4(), manager_id=manager.id)
        other = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = _make_service(payments=MockPaymentRepoWithScoping({owned.id: owned, other.id: other}))

        result = await svc.list_payments(mock_db, current_user=manager)

        assert result.items == [owned]
        assert result.total == 1

    async def test_user_role_is_forbidden(self, mock_db):
        svc = _make_service(payments=MockPaymentRepoWithScoping())
        with pytest.raises(PaymentForbiddenError):
            await svc.list_payments(mock_db, current_user=make_regular_user())


# ─── create_payment ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCreatePayment:
    async def test_admin_can_create_for_any_contract(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        admin = make_admin()
        result = await svc.create_payment(mock_db, _payload(contract_id=contract_id), current_user=admin)

        assert result.contract_id == contract_id
        assert mock_db.commit.called

        mock_db.add.assert_called_once()
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, AuditLog)
        assert row.actor_id == admin.id
        assert row.action == AuditAction.CREATE
        assert row.entity_type == "Payment"
        assert row.entity_id == result.id

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

    async def test_current_user_is_required(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(TypeError):
            await svc.create_payment(mock_db, _payload(contract_id=contract_id))

        assert repo.created_payloads == []

    async def test_user_role_is_forbidden(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(PaymentForbiddenError):
            await svc.create_payment(mock_db, _payload(contract_id=contract_id), current_user=make_regular_user())

        assert repo.created_payloads == []


# ─── create_payment (billing_record_id) ──────────────────────────────────────


def _billing_record(**kwargs):
    defaults = dict(
        id=uuid4(),
        lease_id=uuid4(),
        amount_due=Decimal("15000.00"),
        late_fee_applied=False,
        late_fee_amount_charged=None,
        overpaid_amount=None,
        status=BillingRecordStatus.pending,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
class TestCreatePaymentAgainstBillingRecord:
    async def test_partial_payment_transitions_billing_record_to_partially_paid(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        lease = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        record = _billing_record(lease_id=lease.id, amount_due=Decimal("15000.00"))
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            billing_records={record.id: record},
            leases={lease.id: lease},
        )

        result = await svc.create_payment(
            mock_db,
            _payload(contract_id=contract_id, billing_record_id=record.id, amount=Decimal("5000.00")),
            current_user=make_admin(),
        )

        assert result.billing_record_id == record.id
        assert record.status == BillingRecordStatus.partially_paid
        assert mock_db.commit.called

    async def test_full_payment_transitions_billing_record_to_paid(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        lease = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        record = _billing_record(lease_id=lease.id, amount_due=Decimal("15000.00"))
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            billing_records={record.id: record},
            leases={lease.id: lease},
        )

        await svc.create_payment(
            mock_db,
            _payload(contract_id=contract_id, billing_record_id=record.id, amount=Decimal("15000.00")),
            current_user=make_admin(),
        )

        assert record.status == BillingRecordStatus.paid
        assert record.overpaid_amount is None

    async def test_overpayment_transitions_to_paid_and_records_excess(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        lease = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        record = _billing_record(lease_id=lease.id, amount_due=Decimal("15000.00"))
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            billing_records={record.id: record},
            leases={lease.id: lease},
        )

        await svc.create_payment(
            mock_db,
            _payload(contract_id=contract_id, billing_record_id=record.id, amount=Decimal("15500.00")),
            current_user=make_admin(),
        )

        assert record.status == BillingRecordStatus.paid
        assert record.overpaid_amount == Decimal("500.00")

    async def test_cumulative_across_multiple_payments(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        lease = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        record = _billing_record(lease_id=lease.id, amount_due=Decimal("15000.00"))
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            billing_records={record.id: record},
            leases={lease.id: lease},
        )

        await svc.create_payment(
            mock_db,
            _payload(contract_id=contract_id, billing_record_id=record.id, amount=Decimal("5000.00")),
            current_user=make_admin(),
        )
        assert record.status == BillingRecordStatus.partially_paid

        await svc.create_payment(
            mock_db,
            _payload(contract_id=contract_id, billing_record_id=record.id, amount=Decimal("10000.00")),
            current_user=make_admin(),
        )
        assert record.status == BillingRecordStatus.paid

    async def test_voided_payments_excluded_from_cumulative(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        lease = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        record = _billing_record(lease_id=lease.id, amount_due=Decimal("15000.00"))
        voided = SimpleNamespace(
            id=uuid4(), contract_id=contract_id, billing_record_id=record.id, status=PaymentStatus.VOIDED
        )
        svc = _make_service(
            payments={voided.id: voided},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            billing_records={record.id: record},
            leases={lease.id: lease},
        )

        await svc.create_payment(
            mock_db,
            _payload(contract_id=contract_id, billing_record_id=record.id, amount=Decimal("5000.00")),
            current_user=make_admin(),
        )

        assert record.status == BillingRecordStatus.partially_paid

    async def test_raises_when_billing_record_does_not_exist(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_payment(
                mock_db,
                _payload(contract_id=contract_id, billing_record_id=uuid4()),
                current_user=make_admin(),
            )

    async def test_raises_when_billing_record_belongs_to_different_contract(self, mock_db):
        contract_id, other_contract_id, prop_id = uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=uuid4(), contract_id=other_contract_id)
        record = _billing_record(lease_id=lease.id)
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            billing_records={record.id: record},
            leases={lease.id: lease},
        )

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_payment(
                mock_db,
                _payload(contract_id=contract_id, billing_record_id=record.id),
                current_user=make_admin(),
            )

    async def test_payment_without_billing_record_id_is_unaffected(self, mock_db):
        """Regression: today's contract-only flow keeps working unchanged."""
        contract_id, prop_id = uuid4(), uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.create_payment(mock_db, _payload(contract_id=contract_id), current_user=make_admin())

        assert result.billing_record_id is None
        assert mock_db.commit.called


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

        admin = make_admin()
        result = await svc.update_payment(mock_db, payment_id, PaymentUpdate(status="REFUNDED"), current_user=admin)
        assert result.status == "REFUNDED"
        assert mock_db.commit.called

        row = mock_db.add.call_args.args[0]
        assert row.action == AuditAction.UPDATE
        assert row.entity_type == "Payment"
        assert row.entity_id == payment_id
        assert row.actor_id == admin.id

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

    async def test_current_user_is_required(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status="PAID")
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(TypeError):
            await svc.update_payment(mock_db, payment_id, PaymentUpdate(status="REFUNDED"))

        assert repo.updated_payloads == []

    async def test_user_role_is_forbidden(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status="PAID")
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(PaymentForbiddenError):
            await svc.update_payment(
                mock_db, payment_id, PaymentUpdate(status="REFUNDED"), current_user=make_regular_user()
            )

        assert repo.updated_payloads == []

    async def test_fetches_contract_only_once(self, mock_db):
        """update_payment must not re-fetch the contract it already
        resolved for authorization — see issue #55."""
        manager_id, payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status="PAID")
        contract_repo = MockReadOnlyRepo({contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)})
        svc = _make_service(
            payments={payment_id: payment},
            contracts=contract_repo,
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
        )

        await svc.update_payment(
            mock_db, payment_id, PaymentUpdate(status="REFUNDED"), current_user=make_manager(manager_id)
        )

        assert contract_repo.get_by_id_calls == [contract_id]

    async def test_raises_when_payment_already_voided(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status=PaymentStatus.VOIDED)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(PaymentAlreadyVoidedError):
            await svc.update_payment(mock_db, payment_id, PaymentUpdate(amount=Decimal("1.00")), make_admin())

        assert repo.updated_payloads == []
        assert not mock_db.commit.called


# ─── void_and_correct_payment ────────────────────────────────────────────────


def _correction_payload(**kwargs):
    defaults = dict(amount=Decimal("12000.00"), payment_method="bank transfer")
    defaults.update(kwargs)
    return PaymentCorrectionCreate(**defaults)


class TestPaymentCorrectionCreateEdgeCases:
    def test_mixed_case_payment_method_is_normalized_to_lowercase(self):
        payload = _correction_payload(payment_method="Bank Transfer")
        assert payload.payment_method == "bank transfer"

    def test_invalid_payment_method_still_raises_validation_error(self):
        with pytest.raises(ValidationError):
            _correction_payload(payment_method="bitcoin")


@pytest.mark.asyncio
class TestVoidAndCorrectPayment:
    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.void_and_correct_payment(mock_db, uuid4(), _correction_payload(), make_admin())

    async def test_admin_can_correct_any_payment(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status=PaymentStatus.PAID)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        admin = make_admin()
        result = await svc.void_and_correct_payment(mock_db, payment_id, _correction_payload(), admin)

        assert result.corrects_payment_id == payment_id
        assert result.contract_id == contract_id
        assert result.amount == Decimal("12000.00")
        assert result.status == PaymentStatus.PAID
        assert payment.status == PaymentStatus.VOIDED
        assert mock_db.commit.called

        assert mock_db.add.call_count == 2
        rows = [call.args[0] for call in mock_db.add.call_args_list]
        create_row = next(r for r in rows if r.action == AuditAction.CREATE)
        update_row = next(r for r in rows if r.action == AuditAction.UPDATE)
        assert create_row.entity_type == "Payment"
        assert create_row.entity_id == result.id
        assert update_row.entity_type == "Payment"
        assert update_row.entity_id == payment_id
        assert create_row.actor_id == admin.id
        assert update_row.actor_id == admin.id

    async def test_manager_can_correct_owned_payment(self, mock_db):
        manager_id, payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status=PaymentStatus.PAID)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
        )

        result = await svc.void_and_correct_payment(
            mock_db, payment_id, _correction_payload(), make_manager(manager_id)
        )
        assert result.corrects_payment_id == payment_id
        assert payment.status == PaymentStatus.VOIDED

    async def test_manager_forbidden_for_unowned_payment(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status=PaymentStatus.PAID)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(PaymentForbiddenError):
            await svc.void_and_correct_payment(mock_db, payment_id, _correction_payload(), make_manager())

        assert repo.created_payloads == []
        assert payment.status == PaymentStatus.PAID
        assert not mock_db.commit.called

    async def test_user_role_is_forbidden(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status=PaymentStatus.PAID)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(PaymentForbiddenError):
            await svc.void_and_correct_payment(mock_db, payment_id, _correction_payload(), make_regular_user())

    async def test_current_user_is_required(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status=PaymentStatus.PAID)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(TypeError):
            await svc.void_and_correct_payment(mock_db, payment_id, _correction_payload())

    async def test_raises_when_already_voided(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id, status=PaymentStatus.VOIDED)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(PaymentAlreadyVoidedError):
            await svc.void_and_correct_payment(mock_db, payment_id, _correction_payload(), make_admin())

        assert repo.created_payloads == []
        assert not mock_db.commit.called


# ─── delete_payment ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeletePayment:
    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.delete_payment(mock_db, uuid4(), make_admin())

    async def test_admin_can_delete_any_payment(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        admin = make_admin()
        result = await svc.delete_payment(mock_db, payment_id, current_user=admin)
        assert result is payment
        assert mock_db.commit.called

        row = mock_db.add.call_args.args[0]
        assert row.action == AuditAction.DELETE
        assert row.entity_type == "Payment"
        assert row.entity_id == payment_id
        assert row.actor_id == admin.id

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

    async def test_current_user_is_required(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(TypeError):
            await svc.delete_payment(mock_db, payment_id)

        assert repo.deleted_ids == []

    async def test_user_role_is_forbidden(self, mock_db):
        payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id)
        svc = _make_service(
            payments={payment_id: payment},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.payment_repo

        with pytest.raises(PaymentForbiddenError):
            await svc.delete_payment(mock_db, payment_id, current_user=make_regular_user())

        assert repo.deleted_ids == []

    async def test_fetches_contract_only_once(self, mock_db):
        """delete_payment must not re-fetch the contract it already
        resolved for authorization — see issue #55."""
        manager_id, payment_id, contract_id, prop_id = uuid4(), uuid4(), uuid4(), uuid4()
        payment = SimpleNamespace(id=payment_id, contract_id=contract_id)
        contract_repo = MockReadOnlyRepo({contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)})
        svc = _make_service(
            payments={payment_id: payment},
            contracts=contract_repo,
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
        )

        await svc.delete_payment(mock_db, payment_id, current_user=make_manager(manager_id))

        assert contract_repo.get_by_id_calls == [contract_id]


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
