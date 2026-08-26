import pytest

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.models.audit_log import AuditAction, AuditLog
from app.models.billing_record import BillingRecordStatus
from app.schemas.billing_record import BillingRecordLateFeeCorrection
from app.models.lease import BillingCycle
from app.services.exceptions import (
    BillingRecordAlreadyGeneratedError,
    BillingRecordForbiddenError,
    InvalidBillingRecordTransitionError,
    BillingRecordCorrectionNotAllowedError,
    RelatedResourceNotFoundError,
    ResourceForbiddenError,
)
from app.services.lease_billing_service import LeaseBillingService
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_admin, make_manager, make_regular_user


class MockBillingRecordRepo(MockCRUDRepo):
    async def get_by_lease_and_period(self, db, lease_id, period_start):
        matches = await self._filter_by(lease_id=lease_id, period_start=period_start)
        return matches[0] if matches else None

    async def get_all_for_lease(self, db, lease_id, skip=0, limit=100):
        matches = await self._filter_by(lease_id=lease_id)
        return matches[skip : skip + limit]

    async def count_for_lease(self, db, lease_id):
        return len(await self._filter_by(lease_id=lease_id))

    async def get_latest_for_lease(self, db, lease_id):
        matches = await self._filter_by(lease_id=lease_id)
        if not matches:
            return None
        return max(matches, key=lambda record: record.period_end)


class MockPaymentRepo:
    """Minimal stand-in for PaymentRepository.sum_by_billing_record_ids - LeaseBillingService's
    read path is the only thing here that needs it."""

    def __init__(self, payments=None):
        self.payments = payments or {}

    async def sum_by_billing_record_ids(self, db, billing_record_ids):
        totals: dict = {}
        for payment in self.payments.values():
            if payment.billing_record_id in billing_record_ids and payment.status != "VOIDED":
                totals[payment.billing_record_id] = totals.get(payment.billing_record_id, Decimal("0")) + payment.amount

        return totals


def _make_service(
    billing_records=None,
    leases=None,
    contracts=None,
    properties=None,
    payments=None,
) -> LeaseBillingService:

    if billing_records is None:
        billing_record_repo = MockBillingRecordRepo({})
    elif isinstance(billing_records, dict):
        billing_record_repo = MockBillingRecordRepo(billing_records)
    else:
        billing_record_repo = billing_records

    if leases is None:
        lease_repo = MockReadOnlyRepo({})
    elif isinstance(leases, dict):
        lease_repo = MockReadOnlyRepo(leases)
    else:
        lease_repo = leases

    if contracts is None:
        contract_repo = MockReadOnlyRepo({})
    elif isinstance(contracts, dict):
        contract_repo = MockReadOnlyRepo(contracts)
    else:
        contract_repo = contracts

    if properties is None:
        property_repo = MockReadOnlyRepo({})
    elif isinstance(properties, dict):
        property_repo = MockReadOnlyRepo(properties)
    else:
        property_repo = properties

    if payments is None:
        payment_repo = MockPaymentRepo({})
    elif isinstance(payments, dict):
        payment_repo = MockPaymentRepo(payments)
    else:
        payment_repo = payments

    return LeaseBillingService(
        billing_record_repo=billing_record_repo,
        lease_repo=lease_repo,
        contract_repo=contract_repo,
        property_repo=property_repo,
        payment_repo=payment_repo,
    )


def _billing_record(**kwargs):
    defaults = dict(
        id=uuid4(),
        lease_id=uuid4(),
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        due_date=date(2026, 8, 5),
        amount_due=Decimal("15000.00"),
        late_fee_applied=False,
        late_fee_amount_charged=None,
        overpaid_amount=None,
        status=BillingRecordStatus.pending,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _lease(**kwargs):
    defaults = dict(
        id=uuid4(),
        contract_id=uuid4(),
        monthly_rent=Decimal("15000.00"),
        due_day=5,
        billing_cycle=BillingCycle.monthly,
        start_date=date(2026, 8, 1),
        grace_period_days=3,
        late_fee_amount=Decimal("500.00"),
        late_fee_percent=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ─── Class attributes ────────────────────────────────────────────────────────


class TestLeaseBillingServiceClassAttributes:
    def test_forbidden_error_is_billing_record_forbidden_error(self):
        assert LeaseBillingService.forbidden_error is BillingRecordForbiddenError

    def test_billing_record_forbidden_error_is_a_resource_forbidden_error(self):
        assert issubclass(BillingRecordForbiddenError, ResourceForbiddenError)


# ─── State machine (_transition) ─────────────────────────────────────────────
#
# pending: {partially_paid, paid, overdue}
# partially_paid: {paid, overdue, written_off}
# overdue: {partially_paid, paid, written_off}
# paid: {}          (terminal)
# written_off: {}   (terminal)


class TestTransition:
    def test_pending_to_partially_paid_is_valid(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.pending)
        svc._transition(record, BillingRecordStatus.partially_paid)
        assert record.status == BillingRecordStatus.partially_paid

    def test_pending_to_paid_is_valid(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.pending)
        svc._transition(record, BillingRecordStatus.paid)
        assert record.status == BillingRecordStatus.paid

    def test_pending_to_overdue_is_valid(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.pending)
        svc._transition(record, BillingRecordStatus.overdue)
        assert record.status == BillingRecordStatus.overdue

    def test_partially_paid_to_paid_is_valid(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.partially_paid)
        svc._transition(record, BillingRecordStatus.paid)
        assert record.status == BillingRecordStatus.paid

    def test_partially_paid_to_overdue_is_valid(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.partially_paid)
        svc._transition(record, BillingRecordStatus.overdue)
        assert record.status == BillingRecordStatus.overdue

    def test_partially_paid_to_written_off_is_valid(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.partially_paid)
        svc._transition(record, BillingRecordStatus.written_off)
        assert record.status == BillingRecordStatus.written_off

    def test_overdue_to_partially_paid_is_valid(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.overdue)
        svc._transition(record, BillingRecordStatus.partially_paid)
        assert record.status == BillingRecordStatus.partially_paid

    def test_overdue_to_paid_is_valid(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.overdue)
        svc._transition(record, BillingRecordStatus.paid)
        assert record.status == BillingRecordStatus.paid

    def test_overdue_to_written_off_is_valid(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.overdue)
        svc._transition(record, BillingRecordStatus.written_off)
        assert record.status == BillingRecordStatus.written_off

    def test_paid_is_terminal(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.paid)
        with pytest.raises(InvalidBillingRecordTransitionError):
            svc._transition(record, BillingRecordStatus.pending)
        assert record.status == BillingRecordStatus.paid

    def test_written_off_is_terminal(self):
        svc = _make_service()
        record = _billing_record(status=BillingRecordStatus.written_off)
        with pytest.raises(InvalidBillingRecordTransitionError):
            svc._transition(record, BillingRecordStatus.paid)
        assert record.status == BillingRecordStatus.written_off


# ─── generate_billing_record ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGenerateBillingRecord:
    async def test_admin_can_generate_billing_record(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        svc = _make_service(
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        admin = make_admin()
        result = await svc.generate_billing_record(mock_db, lease.id, current_user=admin)

        assert result.lease_id == lease.id
        assert result.period_start == lease.start_date
        assert result.period_end == lease.start_date + timedelta(days=30)
        assert result.due_date == lease.start_date + timedelta(days=lease.due_day)
        assert result.amount_due == lease.monthly_rent
        assert result.status == BillingRecordStatus.pending
        assert mock_db.commit.called

        mock_db.add.assert_called_once()
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, AuditLog)
        assert row.actor_id == admin.id
        assert row.action == AuditAction.CREATE
        assert row.entity_type == "BillingRecord"
        assert row.entity_id == result.id

    async def test_first_period_starts_on_lease_start_date_not_calendar_month(self, mock_db):
        """A lease starting mid-month (e.g. Aug 18) must never be billed for
        days before it started — the first period starts exactly on
        start_date, not the 1st of that calendar month."""
        lease = _lease(start_date=date(2026, 8, 18))
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        svc = _make_service(
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        result = await svc.generate_billing_record(mock_db, lease.id, current_user=make_admin())

        assert result.period_start == date(2026, 8, 18)
        assert result.period_end == date(2026, 9, 17)
        assert result.due_date >= result.period_start

    async def test_second_call_generates_the_next_contiguous_period(self, mock_db):
        """No gap between periods: the second call's period_start picks up
        exactly where the first left off, so no day of the lease's term is
        ever left unbilled."""
        lease = _lease(start_date=date(2026, 8, 18))
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        svc = _make_service(
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        first = await svc.generate_billing_record(mock_db, lease.id, current_user=make_admin())
        second = await svc.generate_billing_record(mock_db, lease.id, current_user=make_admin())

        assert second.period_start == first.period_end + timedelta(days=1)
        assert second.period_end == second.period_start + timedelta(days=30)

    async def test_due_day_is_a_plain_offset_not_a_calendar_day(self, mock_db):
        """due_day is now "days after period_start", not a calendar
        day-of-month — nothing clamps it to end-of-period anymore."""
        lease = _lease(due_day=31)
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        svc = _make_service(
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        result = await svc.generate_billing_record(mock_db, lease.id, current_user=make_admin())

        assert result.due_date == lease.start_date + timedelta(days=31)

    async def test_manager_can_generate_for_owned_property(self, mock_db):
        manager_id = uuid4()
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        svc = _make_service(
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=manager_id)},
        )

        result = await svc.generate_billing_record(mock_db, lease.id, current_user=make_manager(manager_id))
        assert result.lease_id == lease.id

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        svc = _make_service(
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )
        repo = svc.billing_record_repo

        with pytest.raises(BillingRecordForbiddenError):
            await svc.generate_billing_record(mock_db, lease.id, current_user=make_manager())

        assert repo.created_payloads == []
        assert not mock_db.commit.called

    async def test_user_role_is_forbidden(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        svc = _make_service(
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        with pytest.raises(BillingRecordForbiddenError):
            await svc.generate_billing_record(mock_db, lease.id, current_user=make_regular_user())

    async def test_raises_when_lease_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.generate_billing_record(mock_db, uuid4(), current_user=make_admin())

    async def test_current_user_is_required(self, mock_db):
        lease = _lease()
        svc = _make_service(leases={lease.id: lease})
        with pytest.raises(TypeError):
            await svc.generate_billing_record(mock_db, lease.id)

    async def test_translates_integrity_error_into_already_generated(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())

        class Repo(MockBillingRecordRepo):
            async def create(self, db, payload):
                raise IntegrityError(
                    "INSERT",
                    {},
                    Exception(
                        'duplicate key value violates unique constraint "uq_billing_record_lease_id_period_start"'
                    ),
                )

        svc = _make_service(
            billing_records=Repo(),
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        with pytest.raises(BillingRecordAlreadyGeneratedError):
            await svc.generate_billing_record(mock_db, lease.id, current_user=make_admin())

        assert not mock_db.add.called
        assert not mock_db.commit.called

    async def test_concurrent_calls_computing_the_same_period_do_not_create_a_duplicate(self, mock_db):
        """Idempotency under a race: if two requests both read "no records
        yet" before either commits (get_latest_for_lease returns None for
        both), they'd both compute the same period_start — the second
        create() then hits the DB's uniqueness constraint and raises a
        specific, catchable error rather than silently duplicating."""
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())

        class RacingRepo(MockBillingRecordRepo):
            async def get_latest_for_lease(self, db, lease_id):
                return None

        svc = _make_service(
            billing_records=RacingRepo(),
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )
        repo = svc.billing_record_repo

        original_create = repo.create

        async def create_with_constraint(db, payload):
            existing = await repo.get_by_lease_and_period(db, payload.lease_id, payload.period_start)
            if existing is not None:
                raise IntegrityError(
                    "INSERT",
                    {},
                    Exception(
                        'duplicate key value violates unique constraint "uq_billing_record_lease_id_period_start"'
                    ),
                )
            return await original_create(db, payload)

        repo.create = create_with_constraint

        await svc.generate_billing_record(mock_db, lease.id, current_user=make_admin())

        with pytest.raises(BillingRecordAlreadyGeneratedError):
            await svc.generate_billing_record(mock_db, lease.id, current_user=make_admin())

        assert len(repo.records) == 1

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())

        class Repo(MockBillingRecordRepo):
            async def create(self, db, payload):
                raise IntegrityError("INSERT", {}, Exception("some other integrity problem"))

        svc = _make_service(
            billing_records=Repo(),
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        with pytest.raises(IntegrityError):
            await svc.generate_billing_record(mock_db, lease.id, current_user=make_admin())


# ─── evaluate_overdue ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEvaluateOverdue:
    async def test_applies_flat_late_fee_once_overdue(self, mock_db):
        lease = _lease(grace_period_days=3, late_fee_amount=Decimal("500.00"), late_fee_percent=None)
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(
            lease_id=lease.id,
            due_date=date(2026, 8, 5),
            amount_due=Decimal("15000.00"),
            status=BillingRecordStatus.pending,
        )
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        result = await svc.evaluate_overdue(mock_db, record.id, current_user=make_admin(), as_of=date(2026, 8, 9))

        assert result.status == BillingRecordStatus.overdue
        assert result.late_fee_applied is True
        assert result.late_fee_amount_charged == Decimal("500.00")
        assert mock_db.commit.called

    async def test_applies_percent_late_fee_rounded_to_two_decimals(self, mock_db):
        lease = _lease(grace_period_days=0, late_fee_amount=None, late_fee_percent=Decimal("5.5"))
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(
            lease_id=lease.id,
            due_date=date(2026, 8, 5),
            amount_due=Decimal("15000.00"),
            status=BillingRecordStatus.pending,
        )
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        result = await svc.evaluate_overdue(mock_db, record.id, current_user=make_admin(), as_of=date(2026, 8, 6))

        assert result.status == BillingRecordStatus.overdue
        assert result.late_fee_amount_charged == Decimal("825.00")

    async def test_before_grace_period_is_a_noop(self, mock_db):
        lease = _lease(grace_period_days=5, late_fee_amount=Decimal("500.00"), late_fee_percent=None)
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(
            lease_id=lease.id,
            due_date=date(2026, 8, 5),
            status=BillingRecordStatus.pending,
        )
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        result = await svc.evaluate_overdue(mock_db, record.id, current_user=make_admin(), as_of=date(2026, 8, 8))

        assert result.status == BillingRecordStatus.pending
        assert result.late_fee_applied is False
        assert not mock_db.commit.called

    async def test_does_not_reapply_fee_once_already_applied(self, mock_db):
        lease = _lease(grace_period_days=3, late_fee_amount=Decimal("500.00"), late_fee_percent=None)
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(
            lease_id=lease.id,
            due_date=date(2026, 8, 5),
            status=BillingRecordStatus.overdue,
            late_fee_applied=True,
            late_fee_amount_charged=Decimal("500.00"),
        )
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        result = await svc.evaluate_overdue(mock_db, record.id, current_user=make_admin(), as_of=date(2026, 9, 1))

        assert result.late_fee_amount_charged == Decimal("500.00")

    async def test_raises_when_billing_record_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.evaluate_overdue(mock_db, uuid4(), current_user=make_admin())

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id, status=BillingRecordStatus.pending)
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        with pytest.raises(BillingRecordForbiddenError):
            await svc.evaluate_overdue(mock_db, record.id, current_user=make_manager())


# ─── list_for_lease ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListForLease:
    async def test_admin_lists_records_for_lease(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id)
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        result = await svc.list_for_lease(mock_db, lease.id, current_user=make_admin())

        assert result.total == 1
        assert result.items == [record]

    async def test_manager_can_list_for_owned_property(self, mock_db):
        manager_id = uuid4()
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id)
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=manager_id)},
        )

        result = await svc.list_for_lease(mock_db, lease.id, current_user=make_manager(manager_id))

        assert result.total == 1

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        svc = _make_service(
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        with pytest.raises(BillingRecordForbiddenError):
            await svc.list_for_lease(mock_db, lease.id, current_user=make_manager())

    async def test_raises_when_lease_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.list_for_lease(mock_db, uuid4(), current_user=make_admin())


# ─── get_billing_record ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetBillingRecord:
    async def test_admin_can_get_billing_record(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id)
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        result = await svc.get_billing_record(mock_db, record.id, current_user=make_admin())

        assert result is record

    async def test_manager_can_get_for_owned_property(self, mock_db):
        manager_id = uuid4()
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id)
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=manager_id)},
        )

        result = await svc.get_billing_record(mock_db, record.id, current_user=make_manager(manager_id))

        assert result is record

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id)
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=uuid4())},
        )

        with pytest.raises(BillingRecordForbiddenError):
            await svc.get_billing_record(mock_db, record.id, current_user=make_manager())

    async def test_raises_when_billing_record_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_billing_record(mock_db, uuid4(), current_user=make_admin())


# ─── apply_payment ────────────────────────────────────────────────────────────


class TestApplyPayment:
    def test_partial_cumulative_transitions_pending_to_partially_paid(self):
        svc = _make_service()
        record = _billing_record(amount_due=Decimal("15000.00"), status=BillingRecordStatus.pending)

        svc.apply_payment(record, Decimal("5000.00"))

        assert record.status == BillingRecordStatus.partially_paid
        assert record.overpaid_amount is None

    def test_exact_cumulative_transitions_to_paid(self):
        svc = _make_service()
        record = _billing_record(amount_due=Decimal("15000.00"), status=BillingRecordStatus.pending)

        svc.apply_payment(record, Decimal("15000.00"))

        assert record.status == BillingRecordStatus.paid
        assert record.overpaid_amount is None

    def test_overpayment_transitions_to_paid_and_records_excess(self):
        svc = _make_service()
        record = _billing_record(amount_due=Decimal("15000.00"), status=BillingRecordStatus.pending)

        svc.apply_payment(record, Decimal("15500.00"))

        assert record.status == BillingRecordStatus.paid
        assert record.overpaid_amount == Decimal("500.00")

    def test_amount_due_includes_late_fee_when_present(self):
        """A record with an applied late fee isn't 'paid' until amount_due
        + late_fee_amount_charged is covered."""
        svc = _make_service()
        record = _billing_record(
            amount_due=Decimal("15000.00"),
            status=BillingRecordStatus.overdue,
            late_fee_applied=True,
            late_fee_amount_charged=Decimal("500.00"),
        )

        svc.apply_payment(record, Decimal("15000.00"))
        assert record.status == BillingRecordStatus.partially_paid

        svc.apply_payment(record, Decimal("15500.00"))
        assert record.status == BillingRecordStatus.paid
        assert record.overpaid_amount is None

    def test_further_payment_after_paid_increases_overpaid_amount(self):
        svc = _make_service()
        record = _billing_record(amount_due=Decimal("15000.00"), status=BillingRecordStatus.paid)

        svc.apply_payment(record, Decimal("15200.00"))

        assert record.status == BillingRecordStatus.paid
        assert record.overpaid_amount == Decimal("200.00")

    def test_overdue_to_partially_paid_is_a_valid_transition(self):
        svc = _make_service()
        record = _billing_record(amount_due=Decimal("15000.00"), status=BillingRecordStatus.overdue)

        svc.apply_payment(record, Decimal("5000.00"))

        assert record.status == BillingRecordStatus.partially_paid

    def test_written_off_does_not_transition(self):
        """written_off is terminal — a stray payment against it shouldn't
        resurrect the record into partially_paid/paid."""
        svc = _make_service()
        record = _billing_record(amount_due=Decimal("15000.00"), status=BillingRecordStatus.written_off)

        svc.apply_payment(record, Decimal("15000.00"))

        assert record.status == BillingRecordStatus.written_off


# ─── write_off_billing_record ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestWriteOffBillingRecord:
    async def _setup(self, status, manager_id=None):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id, status=status)
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={
                contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=manager_id or uuid4())
            },
        )
        return svc, record

    async def test_write_off_from_partially_paid_succeeds(self, mock_db):
        svc, record = await self._setup(BillingRecordStatus.partially_paid)
        result = await svc.write_off_billing_record(mock_db, record.id, current_user=make_admin())
        assert result.status == BillingRecordStatus.written_off
        assert mock_db.commit.called

    async def test_write_off_from_overdue_succeeds(self, mock_db):
        svc, record = await self._setup(BillingRecordStatus.overdue)
        result = await svc.write_off_billing_record(mock_db, record.id, current_user=make_admin())
        assert result.status == BillingRecordStatus.written_off

    async def test_write_off_from_pending_raises(self, mock_db):
        svc, record = await self._setup(BillingRecordStatus.pending)
        with pytest.raises(InvalidBillingRecordTransitionError):
            await svc.write_off_billing_record(mock_db, record.id, current_user=make_admin())

    async def test_write_off_from_paid_raises(self, mock_db):
        svc, record = await self._setup(BillingRecordStatus.paid)
        with pytest.raises(InvalidBillingRecordTransitionError):
            await svc.write_off_billing_record(mock_db, record.id, current_user=make_admin())

    async def test_write_off_already_written_off_raises(self, mock_db):
        svc, record = await self._setup(BillingRecordStatus.written_off)
        with pytest.raises(InvalidBillingRecordTransitionError):
            await svc.write_off_billing_record(mock_db, record.id, current_user=make_admin())

    async def test_missing_billing_record_raises_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.write_off_billing_record(mock_db, uuid4(), current_user=make_admin())

    async def test_manager_can_write_off_owned_property(self, mock_db):
        manager = make_manager()
        svc, record = await self._setup(BillingRecordStatus.overdue, manager_id=manager.id)
        result = await svc.write_off_billing_record(mock_db, record.id, current_user=manager)
        assert result.status == BillingRecordStatus.written_off

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        svc, record = await self._setup(BillingRecordStatus.overdue, manager_id=uuid4())
        with pytest.raises(BillingRecordForbiddenError):
            await svc.write_off_billing_record(mock_db, record.id, current_user=make_manager())

    async def test_writes_audit_log(self, mock_db):
        svc, record = await self._setup(BillingRecordStatus.overdue)
        admin = make_admin()
        await svc.write_off_billing_record(mock_db, record.id, current_user=admin)
        mock_db.add.assert_called_once()
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, AuditLog)
        assert row.action == AuditAction.UPDATE
        assert row.entity_type == "BillingRecord"
        assert row.entity_id == record.id


# ─── correct_late_fee ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCorrectLateFee:
    async def _setup(self, status, manager_id=None):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id, status=status)
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            properties={
                contract.property_id: SimpleNamespace(id=contract.property_id, manager_id=manager_id or uuid4())
            },
        )
        return svc, record

    @pytest.mark.parametrize(
        "status",
        [BillingRecordStatus.pending, BillingRecordStatus.partially_paid, BillingRecordStatus.overdue],
    )
    async def test_updates_fields_on_non_terminal_status(self, mock_db, status):
        svc, record = await self._setup(status)
        payload = BillingRecordLateFeeCorrection(late_fee_applied=True, late_fee_amount_charged=Decimal("250.00"))
        result = await svc.correct_late_fee(mock_db, record.id, payload, current_user=make_admin())
        assert result.late_fee_applied is True
        assert result.late_fee_amount_charged == Decimal("250.00")

    async def test_can_clear_an_erroneous_late_fee(self, mock_db):
        svc, record = await self._setup(
            BillingRecordStatus.overdue,
        )
        record.late_fee_applied = True
        record.late_fee_amount_charged = Decimal("500.00")
        payload = BillingRecordLateFeeCorrection(late_fee_applied=False, late_fee_amount_charged=None)
        result = await svc.correct_late_fee(mock_db, record.id, payload, current_user=make_admin())
        assert result.late_fee_applied is False
        assert result.late_fee_amount_charged is None

    @pytest.mark.parametrize("status", [BillingRecordStatus.paid, BillingRecordStatus.written_off])
    async def test_raises_on_terminal_status(self, mock_db, status):
        svc, record = await self._setup(status)
        payload = BillingRecordLateFeeCorrection(late_fee_applied=True, late_fee_amount_charged=Decimal("100.00"))
        with pytest.raises(BillingRecordCorrectionNotAllowedError):
            await svc.correct_late_fee(mock_db, record.id, payload, current_user=make_admin())

    async def test_missing_billing_record_raises_not_found(self, mock_db):
        svc = _make_service()
        payload = BillingRecordLateFeeCorrection(late_fee_applied=False, late_fee_amount_charged=None)
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.correct_late_fee(mock_db, uuid4(), payload, current_user=make_admin())

    async def test_manager_can_correct_owned_property(self, mock_db):
        manager = make_manager()
        svc, record = await self._setup(BillingRecordStatus.overdue, manager_id=manager.id)
        payload = BillingRecordLateFeeCorrection(late_fee_applied=True, late_fee_amount_charged=Decimal("300.00"))
        result = await svc.correct_late_fee(mock_db, record.id, payload, current_user=manager)
        assert result.late_fee_amount_charged == Decimal("300.00")

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        svc, record = await self._setup(BillingRecordStatus.overdue, manager_id=uuid4())
        payload = BillingRecordLateFeeCorrection(late_fee_applied=True, late_fee_amount_charged=Decimal("100.00"))
        with pytest.raises(BillingRecordForbiddenError):
            await svc.correct_late_fee(mock_db, record.id, payload, current_user=make_manager())

    async def test_writes_audit_log(self, mock_db):
        svc, record = await self._setup(BillingRecordStatus.overdue)
        admin = make_admin()
        payload = BillingRecordLateFeeCorrection(late_fee_applied=True, late_fee_amount_charged=Decimal("100.00"))
        await svc.correct_late_fee(mock_db, record.id, payload, current_user=admin)
        row = mock_db.add.call_args.args[0]
        assert row.action == AuditAction.UPDATE
        assert row.entity_type == "BillingRecord"


class TestBillingRecordLateFeeCorrectionSchema:
    def test_requires_amount_when_applied_true(self):
        with pytest.raises(ValueError):
            BillingRecordLateFeeCorrection(late_fee_applied=True, late_fee_amount_charged=None)

    def test_rejects_amount_when_applied_false(self):
        with pytest.raises(ValueError):
            BillingRecordLateFeeCorrection(late_fee_applied=False, late_fee_amount_charged=Decimal("10.00"))


# ─── remaining_balance (read path) ───────────────────────────────────────────


@pytest.mark.asyncio
class TestRemainingBalance:
    async def test_get_billing_record_computes_remaining_balance_with_no_payments(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id, amount_due=Decimal("15000.00"))
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
        )

        result = await svc.get_billing_record(mock_db, record.id, current_user=make_admin())
        assert result.remaining_balance == Decimal("15000.00")

    async def test_partial_payment_reduces_remaining_balance(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id, amount_due=Decimal("15000.00"))
        payment = SimpleNamespace(billing_record_id=record.id, amount=Decimal("5000.00"), status="PAID")
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            payments={payment.billing_record_id: payment},
        )

        result = await svc.get_billing_record(mock_db, record.id, current_user=make_admin())
        assert result.remaining_balance == Decimal("10000.00")

    async def test_overpayment_floors_remaining_balance_at_zero(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(
            lease_id=lease.id,
            amount_due=Decimal("15000.00"),
            status=BillingRecordStatus.paid,
            overpaid_amount=Decimal("500.00"),
        )
        payment = SimpleNamespace(billing_record_id=record.id, amount=Decimal("15500.00"), status="PAID")
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            payments={payment.billing_record_id: payment},
        )

        result = await svc.get_billing_record(mock_db, record.id, current_user=make_admin())
        assert result.remaining_balance == Decimal("0")

    async def test_voided_payments_excluded_from_remaining_balance(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(lease_id=lease.id, amount_due=Decimal("15000.00"))
        payment = SimpleNamespace(billing_record_id=record.id, amount=Decimal("15000.00"), status="VOIDED")
        svc = _make_service(
            billing_records={record.id: record},
            leases={lease.id: lease},
            contracts={contract.id: contract},
            payments={payment.billing_record_id: payment},
        )

        result = await svc.get_billing_record(mock_db, record.id, current_user=make_admin())
        assert result.remaining_balance == Decimal("15000.00")

    async def test_late_fee_counts_toward_total_owed(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record = _billing_record(
            lease_id=lease.id,
            amount_due=Decimal("15000.00"),
            late_fee_applied=True,
            late_fee_amount_charged=Decimal("500.00"),
            status=BillingRecordStatus.overdue,
        )
        svc = _make_service(
            billing_records={record.id: record}, leases={lease.id: lease}, contracts={contract.id: contract}
        )

        result = await svc.get_billing_record(mock_db, record.id, current_user=make_admin())
        assert result.remaining_balance == Decimal("15500.00")

    async def test_list_for_lease_attaches_remaining_balance_to_every_item(self, mock_db):
        lease = _lease()
        contract = SimpleNamespace(id=lease.contract_id, property_id=uuid4())
        record_a = _billing_record(lease_id=lease.id, amount_due=Decimal("15000.00"))
        record_b = _billing_record(lease_id=lease.id, amount_due=Decimal("10000.00"))
        svc = _make_service(
            billing_records={record_a.id: record_a, record_b.id: record_b},
            leases={lease.id: lease},
            contracts={contract.id: contract},
        )

        result = await svc.list_for_lease(mock_db, lease.id, current_user=make_admin())
        balances = {item.id: item.remaining_balance for item in result.items}
        assert balances == {record_a.id: Decimal("15000.00"), record_b.id: Decimal("10000.00")}
