import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.billing_record import BillingRecord, UNPAID_STATUSES
from app.models.contract import Contract
from app.models.lease import Lease
from app.models.property import Property
from app.schemas.billing_record import BillingRecordCreate, BillingRecordUpdate


class BillingRecordRepository(BaseRepository[BillingRecord, BillingRecordCreate, BillingRecordUpdate]):
    """
    BillingRecord-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    async def get_by_lease_and_period(
        self,
        db: AsyncSession,
        lease_id: uuid.UUID,
        period_start: date,
    ) -> BillingRecord | None:
        return await self._first(
            db,
            self.model.lease_id == lease_id,
            self.model.period_start == period_start,
        )

    async def get_all_for_lease(
        self,
        db: AsyncSession,
        lease_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[BillingRecord]:
        return await self._all(db, self.model.lease_id == lease_id, offset=skip, limit=limit)

    async def get_latest_for_lease(self, db: AsyncSession, lease_id: uuid.UUID) -> BillingRecord | None:
        """Most recent billing period generated for this lease so far
        (highest `period_end`), used by `LeaseBillingService` to anchor the
        next period to lease.start_date + N contiguous cycles rather than
        letting a caller pick an arbitrary period_start."""
        return await self._first(
            db,
            self.model.lease_id == lease_id,
            order_by=self.model.period_end.desc(),
        )

    async def count_for_lease(self, db: AsyncSession, lease_id: uuid.UUID) -> int:
        return await self._count(db, self.model.lease_id == lease_id)

    async def sum_outstanding(self, db: AsyncSession) -> Decimal:
        """Total still owed (amount_due + any charged late fee) across
        every non-terminal (not paid/written_off) billing record."""
        stmt = select(
            func.sum(BillingRecord.amount_due + func.coalesce(BillingRecord.late_fee_amount_charged, 0))
        ).where(BillingRecord.status.in_(UNPAID_STATUSES))
        result = await db.execute(stmt)
        return result.scalar_one() or Decimal("0")

    async def sum_outstanding_for_manager(self, db: AsyncSession, manager_id: uuid.UUID) -> Decimal:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(func.sum(BillingRecord.amount_due + func.coalesce(BillingRecord.late_fee_amount_charged, 0)))
            .join(Lease, Lease.id == BillingRecord.lease_id)
            .join(Contract, Contract.id == Lease.contract_id)
            .where(
                BillingRecord.status.in_(UNPAID_STATUSES),
                Contract.property_id.in_(owned_property_ids),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one() or Decimal("0")

    async def sum_credits(self, db: AsyncSession) -> Decimal:
        """Total net overpayment credit — `overpaid_amount` is only ever set on
        terminal `paid` records (see `LeaseBillingService.apply_payment`), which
        `sum_outstanding` already excludes, so this is a disjoint figure rather
        than something to net into `sum_outstanding`."""
        stmt = select(func.sum(BillingRecord.overpaid_amount)).where(BillingRecord.overpaid_amount.isnot(None))
        result = await db.execute(stmt)
        return result.scalar_one() or Decimal("0")

    async def sum_credits_for_manager(self, db: AsyncSession, manager_id: uuid.UUID) -> Decimal:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(func.sum(BillingRecord.overpaid_amount))
            .join(Lease, Lease.id == BillingRecord.lease_id)
            .join(Contract, Contract.id == Lease.contract_id)
            .where(
                BillingRecord.overpaid_amount.isnot(None),
                Contract.property_id.in_(owned_property_ids),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one() or Decimal("0")

    async def get_unpaid_with_grace(self, db: AsyncSession) -> Sequence[Row]:
        """Every non-terminal billing record, paired with its lease's
        grace_period_days — lateness itself is computed in Python by the
        caller (see DashboardService.late_payments), not here."""
        stmt = (
            select(BillingRecord, Lease.grace_period_days)
            .join(Lease, Lease.id == BillingRecord.lease_id)
            .where(BillingRecord.status.in_(UNPAID_STATUSES))
        )
        result = await db.execute(stmt)
        return result.all()

    async def get_unpaid_with_grace_for_manager(self, db: AsyncSession, manager_id: uuid.UUID) -> Sequence[Row]:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(BillingRecord, Lease.grace_period_days)
            .join(Lease, Lease.id == BillingRecord.lease_id)
            .join(Contract, Contract.id == Lease.contract_id)
            .where(
                BillingRecord.status.in_(UNPAID_STATUSES),
                Contract.property_id.in_(owned_property_ids),
            )
        )
        result = await db.execute(stmt)
        return result.all()


# Instantiate once — import this instance everywhere
billing_record_repo = BillingRecordRepository(BillingRecord)
