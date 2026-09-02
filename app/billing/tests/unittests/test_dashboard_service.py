import pytest
import uuid

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.identity.models.user import UserRole
from app.billing.services.dashboard_service import DashboardService
from app.core.services.exceptions import DashboardForbiddenError


class MockPropertyRepo:
    def __init__(self, vacant=0, vacant_for_manager=0):
        self.vacant = vacant
        self.vacant_for_manager = vacant_for_manager
        self.count_vacant_for_manager_calls = []

    async def count_vacant(self, db):
        return self.vacant

    async def count_vacant_for_manager(self, db, manager_id):
        self.count_vacant_for_manager_calls.append(manager_id)
        return self.vacant_for_manager


class MockPaymentRepo:
    def __init__(
        self, collected=Decimal("0"), collected_for_manager=Decimal("0"), recent=None, recent_for_manager=None
    ):
        self.collected = collected
        self.collected_for_manager = collected_for_manager
        self.recent = recent or []
        self.recent_for_manager = recent_for_manager or []
        self.sum_collected_calls = []
        self.sum_collected_for_manager_calls = []

    async def sum_collected(self, db, start, end):
        self.sum_collected_calls.append((start, end))
        return self.collected

    async def sum_collected_for_manager(self, db, manager_id, start, end):
        self.sum_collected_for_manager_calls.append((manager_id, start, end))
        return self.collected_for_manager

    async def get_recent(self, db, limit=10):
        return self.recent[:limit]

    async def get_recent_for_manager(self, db, manager_id, limit=10):
        return self.recent_for_manager[:limit]

    async def sum_by_billing_record_ids(self, db, billing_record_ids):
        return {}


class MockBillingRecordRepo:
    def __init__(
        self,
        outstanding=Decimal("0"),
        outstanding_for_manager=Decimal("0"),
        credits=Decimal("0"),
        credits_for_manager=Decimal("0"),
        unpaid=None,
        unpaid_for_manager=None,
    ):
        self.outstanding = outstanding
        self.outstanding_for_manager = outstanding_for_manager
        self.credits = credits
        self.credits_for_manager = credits_for_manager
        self.unpaid = unpaid or []
        self.unpaid_for_manager = unpaid_for_manager or []

    async def sum_outstanding(self, db):
        return self.outstanding

    async def sum_outstanding_for_manager(self, db, manager_id):
        return self.outstanding_for_manager

    async def sum_credits(self, db):
        return self.credits

    async def sum_credits_for_manager(self, db, manager_id):
        return self.credits_for_manager

    async def get_unpaid_with_grace(self, db):
        return self.unpaid

    async def get_unpaid_with_grace_for_manager(self, db, manager_id):
        return self.unpaid_for_manager


class MockLeaseRepo:
    def __init__(self, expiring=None, expiring_for_manager=None):
        self.expiring = expiring or []
        self.expiring_for_manager = expiring_for_manager or []
        self.get_expiring_calls = []
        self.get_expiring_for_manager_calls = []

    async def get_expiring(self, db, start, end):
        self.get_expiring_calls.append((start, end))
        return self.expiring

    async def get_expiring_for_manager(self, db, manager_id, start, end):
        self.get_expiring_for_manager_calls.append((manager_id, start, end))
        return self.expiring_for_manager


def _billing_record(due_date, status="pending", amount_due=Decimal("1000.00")):
    return SimpleNamespace(
        id=uuid.uuid4(), due_date=due_date, status=status, amount_due=amount_due, late_fee_amount_charged=None
    )


def _make_service(property_repo=None, payment_repo=None, billing_record_repo=None, lease_repo=None) -> DashboardService:
    return DashboardService(
        property_repo=property_repo or MockPropertyRepo(),
        payment_repo=payment_repo or MockPaymentRepo(),
        billing_record_repo=billing_record_repo or MockBillingRecordRepo(),
        lease_repo=lease_repo or MockLeaseRepo(),
    )


def _admin():
    return SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)


def _manager(manager_id=None):
    return SimpleNamespace(id=manager_id or uuid.uuid4(), role=UserRole.MANAGER)


def _user():
    return SimpleNamespace(id=uuid.uuid4(), role=UserRole.USER)


@pytest.mark.asyncio
class TestVacantUnits:
    async def test_admin_sees_unscoped_count(self, mock_db):
        svc = _make_service(property_repo=MockPropertyRepo(vacant=5))
        assert await svc.vacant_units(mock_db, current_user=_admin()) == 5

    async def test_manager_sees_scoped_count(self, mock_db):
        manager = _manager()
        svc = _make_service(property_repo=MockPropertyRepo(vacant_for_manager=2))
        assert await svc.vacant_units(mock_db, current_user=manager) == 2

    async def test_other_role_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(DashboardForbiddenError):
            await svc.vacant_units(mock_db, current_user=_user())


@pytest.mark.asyncio
class TestCollectedThisMonth:
    async def test_admin_sees_unscoped_sum(self, mock_db):
        svc = _make_service(payment_repo=MockPaymentRepo(collected=Decimal("1500.00")))
        assert await svc.collected_this_month(mock_db, current_user=_admin()) == Decimal("1500.00")

    async def test_manager_sees_scoped_sum(self, mock_db):
        svc = _make_service(payment_repo=MockPaymentRepo(collected_for_manager=Decimal("500.00")))
        assert await svc.collected_this_month(mock_db, current_user=_manager()) == Decimal("500.00")

    async def test_other_role_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(DashboardForbiddenError):
            await svc.collected_this_month(mock_db, current_user=_user())

    async def test_window_covers_the_full_current_month(self, mock_db):
        repo = MockPaymentRepo()
        svc = _make_service(payment_repo=repo)
        await svc.collected_this_month(mock_db, current_user=_admin())

        start, end = repo.sum_collected_calls[0]
        today = date.today()
        assert start.date() == today.replace(day=1)
        assert end.date().month == today.month
        assert end.date() >= today


@pytest.mark.asyncio
class TestOutstanding:
    async def test_admin_sees_unscoped_sum(self, mock_db):
        svc = _make_service(billing_record_repo=MockBillingRecordRepo(outstanding=Decimal("2000.00")))
        assert await svc.outstanding(mock_db, current_user=_admin()) == Decimal("2000.00")

    async def test_manager_sees_scoped_sum(self, mock_db):
        svc = _make_service(billing_record_repo=MockBillingRecordRepo(outstanding_for_manager=Decimal("300.00")))
        assert await svc.outstanding(mock_db, current_user=_manager()) == Decimal("300.00")

    async def test_other_role_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(DashboardForbiddenError):
            await svc.outstanding(mock_db, current_user=_user())


@pytest.mark.asyncio
class TestTotalCredits:
    async def test_admin_sees_unscoped_sum(self, mock_db):
        svc = _make_service(billing_record_repo=MockBillingRecordRepo(credits=Decimal("250.00")))
        assert await svc.total_credits(mock_db, current_user=_admin()) == Decimal("250.00")

    async def test_manager_sees_scoped_sum(self, mock_db):
        svc = _make_service(billing_record_repo=MockBillingRecordRepo(credits_for_manager=Decimal("100.00")))
        assert await svc.total_credits(mock_db, current_user=_manager()) == Decimal("100.00")

    async def test_other_role_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(DashboardForbiddenError):
            await svc.total_credits(mock_db, current_user=_user())


@pytest.mark.asyncio
class TestLatePayments:
    async def test_returns_records_past_due_date_plus_grace_period(self, mock_db):
        today = date.today()
        late = _billing_record(due_date=today - timedelta(days=10))
        not_late = _billing_record(due_date=today - timedelta(days=1))
        repo = MockBillingRecordRepo(unpaid=[(late, 3), (not_late, 3)])
        svc = _make_service(billing_record_repo=repo)

        result = await svc.late_payments(mock_db, current_user=_admin())

        assert [r.id for r in result] == [late.id]

    async def test_manager_sees_scoped_records(self, mock_db):
        today = date.today()
        late = _billing_record(due_date=today - timedelta(days=10))
        repo = MockBillingRecordRepo(unpaid_for_manager=[(late, 0)])
        svc = _make_service(billing_record_repo=repo)

        result = await svc.late_payments(mock_db, current_user=_manager())

        assert [r.id for r in result] == [late.id]

    async def test_other_role_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(DashboardForbiddenError):
            await svc.late_payments(mock_db, current_user=_user())


@pytest.mark.asyncio
class TestExpiringLeases:
    async def test_admin_sees_unscoped_leases(self, mock_db):
        lease = SimpleNamespace(id=uuid.uuid4())
        svc = _make_service(lease_repo=MockLeaseRepo(expiring=[lease]))
        assert await svc.expiring_leases(mock_db, current_user=_admin()) == [lease]

    async def test_manager_sees_scoped_leases(self, mock_db):
        lease = SimpleNamespace(id=uuid.uuid4())
        svc = _make_service(lease_repo=MockLeaseRepo(expiring_for_manager=[lease]))
        assert await svc.expiring_leases(mock_db, current_user=_manager()) == [lease]

    async def test_other_role_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(DashboardForbiddenError):
            await svc.expiring_leases(mock_db, current_user=_user())

    async def test_lookahead_days_is_configurable(self, mock_db):
        repo = MockLeaseRepo()
        svc = _make_service(lease_repo=repo)
        await svc.expiring_leases(mock_db, current_user=_admin(), lookahead_days=7)

        start, end = repo.get_expiring_calls[0]
        assert (end - start).days == 7

    async def test_default_lookahead_is_30_days(self, mock_db):
        repo = MockLeaseRepo()
        svc = _make_service(lease_repo=repo)
        await svc.expiring_leases(mock_db, current_user=_admin())

        start, end = repo.get_expiring_calls[0]
        assert (end - start).days == 30


@pytest.mark.asyncio
class TestRecentPayments:
    async def test_admin_sees_unscoped_recent_payments(self, mock_db):
        payment = SimpleNamespace(id=uuid.uuid4())
        svc = _make_service(payment_repo=MockPaymentRepo(recent=[payment]))
        assert await svc.recent_payments(mock_db, current_user=_admin()) == [payment]

    async def test_manager_sees_scoped_recent_payments(self, mock_db):
        payment = SimpleNamespace(id=uuid.uuid4())
        svc = _make_service(payment_repo=MockPaymentRepo(recent_for_manager=[payment]))
        assert await svc.recent_payments(mock_db, current_user=_manager()) == [payment]

    async def test_other_role_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(DashboardForbiddenError):
            await svc.recent_payments(mock_db, current_user=_user())

    async def test_limit_defaults_to_10(self, mock_db):
        payments = [SimpleNamespace(id=uuid.uuid4()) for _ in range(15)]
        svc = _make_service(payment_repo=MockPaymentRepo(recent=payments))
        result = await svc.recent_payments(mock_db, current_user=_admin())
        assert len(result) == 10
