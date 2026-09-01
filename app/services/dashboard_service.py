from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_record import BillingRecord, last_day_of_month
from app.models.user import UserRole
from app.repositories.billing_record import BillingRecordRepository
from app.repositories.lease import LeaseRepository
from app.repositories.payment import PaymentRepository
from app.repositories.property import PropertyRepository
from app.core.services.exceptions import DashboardForbiddenError
from app.core.services.utils import attach_remaining_balance


class DashboardService:
    """
    Read-only landlord dashboard: seven independent aggregation figures over
    Property/Payment/BillingRecord/Lease. Each figure is its own query —
    deliberately not one mega-query joining every entity together.
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        payment_repo: PaymentRepository,
        billing_record_repo: BillingRecordRepository,
        lease_repo: LeaseRepository,
    ) -> None:
        self.property_repo = property_repo
        self.payment_repo = payment_repo
        self.billing_record_repo = billing_record_repo
        self.lease_repo = lease_repo

    @staticmethod
    def _require_manager_or_admin(current_user) -> UserRole:
        role = getattr(current_user, "role", None)
        if role not in (UserRole.ADMIN, UserRole.MANAGER):
            raise DashboardForbiddenError("User not authorized to view dashboard figures.")
        return role

    async def vacant_units(self, db: AsyncSession, current_user) -> int:
        role = self._require_manager_or_admin(current_user)
        if role == UserRole.ADMIN:
            return await self.property_repo.count_vacant(db)
        return await self.property_repo.count_vacant_for_manager(db, current_user.id)

    async def collected_this_month(self, db: AsyncSession, current_user) -> Decimal:
        role = self._require_manager_or_admin(current_user)
        today = datetime.now(timezone.utc).date()
        start = datetime.combine(today.replace(day=1), datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(last_day_of_month(today), datetime.max.time(), tzinfo=timezone.utc)
        if role == UserRole.ADMIN:
            return await self.payment_repo.sum_collected(db, start, end)
        return await self.payment_repo.sum_collected_for_manager(db, current_user.id, start, end)

    async def outstanding(self, db: AsyncSession, current_user) -> Decimal:
        role = self._require_manager_or_admin(current_user)
        if role == UserRole.ADMIN:
            return await self.billing_record_repo.sum_outstanding(db)
        return await self.billing_record_repo.sum_outstanding_for_manager(db, current_user.id)

    async def total_credits(self, db: AsyncSession, current_user) -> Decimal:
        """Net overpayment credit across `paid` billing records - additive to
        `outstanding`, not netted into it (see `BillingRecordRepository.sum_credits`)."""
        role = self._require_manager_or_admin(current_user)

        if role == UserRole.ADMIN:
            return await self.billing_record_repo.sum_credits(db)

        return await self.billing_record_repo.sum_credits_for_manager(db, current_user.id)

    async def late_payments(self, db: AsyncSession, current_user) -> list[BillingRecord]:
        role = self._require_manager_or_admin(current_user)
        if role == UserRole.ADMIN:
            rows = await self.billing_record_repo.get_unpaid_with_grace(db)
        else:
            rows = await self.billing_record_repo.get_unpaid_with_grace_for_manager(db, current_user.id)

        today = date.today()
        records = [
            record for record, grace_period_days in rows if record.due_date + timedelta(days=grace_period_days) < today
        ]
        await attach_remaining_balance(db, records, self.payment_repo)
        return records

    async def expiring_leases(self, db: AsyncSession, current_user, lookahead_days: int = 30) -> list:
        role = self._require_manager_or_admin(current_user)
        today = date.today()
        end = today + timedelta(days=lookahead_days)
        if role == UserRole.ADMIN:
            return await self.lease_repo.get_expiring(db, today, end)
        return await self.lease_repo.get_expiring_for_manager(db, current_user.id, today, end)

    async def recent_payments(self, db: AsyncSession, current_user, limit: int = 10) -> list:
        role = self._require_manager_or_admin(current_user)
        if role == UserRole.ADMIN:
            return await self.payment_repo.get_recent(db, limit=limit)
        return await self.payment_repo.get_recent_for_manager(db, current_user.id, limit=limit)
