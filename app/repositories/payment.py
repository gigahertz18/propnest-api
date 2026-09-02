import uuid

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repositories.base import BaseRepository
from app.models.payment import Payment, PaymentStatus
from app.models.contract import Contract
from app.properties.models.property import Property
from app.schemas.payment import PaymentCreate, PaymentUpdate


class PaymentRepository(BaseRepository[Payment, PaymentCreate, PaymentUpdate]):
    """
    Payment-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    async def get_by_contract(
        self,
        db: AsyncSession,
        contract_id: uuid.UUID,
    ) -> Sequence[Payment]:
        """Return all payments linked to a given contract."""
        return await self._all(db, self.model.contract_id == contract_id)

    async def get_by_status(
        self,
        db: AsyncSession,
        status: str,
    ) -> Sequence[Payment]:
        """Return all payments with a given status (e.g. PAID, PENDING)."""
        return await self._all(db, self.model.status == status)

    async def get_by_billing_record(
        self,
        db: AsyncSession,
        billing_record_id: uuid.UUID,
    ) -> Sequence[Payment]:
        """Return all payments linked to a given billing record."""
        return await self._all(db, self.model.billing_record_id == billing_record_id)

    async def sum_by_billing_record_ids(
        self,
        db: AsyncSession,
        billing_record_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, Decimal]:
        """Sum of non-voided payments per billing record, in one query —
        used by LeaseBillingService's read path to compute remaining_balance
        without N+1'ing across a list of records. Missing keys mean zero
        paid so far; callers should use .get(id, Decimal("0"))."""
        if not billing_record_ids:
            return {}

        stmt = (
            select(Payment.billing_record_id, func.sum(Payment.amount))
            .where(
                Payment.billing_record_id.in_(billing_record_ids),
                Payment.status != PaymentStatus.VOIDED,
            )
            .group_by(Payment.billing_record_id)
        )
        result = await db.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def get_all_for_manager(
        self,
        db: AsyncSession,
        manager_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Payment]:
        """Payments a manager may see — those whose contract belongs to one
        of their own properties (payment.contract_id -> contract.property_id).

        Every payment carries a contract_id (non-nullable), so unlike
        DocumentRepository.get_all_for_manager there's no "unattached
        resource" branch to account for here — every payment resolves to
        exactly one property via its contract.
        """
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(Payment)
            .join(Contract, Contract.id == Payment.contract_id)
            .where(Contract.property_id.in_(owned_property_ids))
            .order_by(Payment.created_at, Payment.id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_all(self, db: AsyncSession) -> int:
        return await self._count(db)

    async def count_all_for_manager(self, db: AsyncSession, manager_id: uuid.UUID) -> int:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(func.count())
            .select_from(Payment)
            .join(Contract, Contract.id == Payment.contract_id)
            .where(Contract.property_id.in_(owned_property_ids))
        )
        result = await db.execute(stmt)
        return int(result.scalar_one())

    async def sum_collected(self, db: AsyncSession, start: datetime, end: datetime) -> Decimal:
        """Total of PAID payments received within [start, end]. Voided/refunded
        payments don't count as "collected" — only PAID does."""
        stmt = select(func.sum(Payment.amount)).where(
            Payment.status == PaymentStatus.PAID,
            Payment.paid_at.between(start, end),
        )
        result = await db.execute(stmt)
        return result.scalar_one() or Decimal("0")

    async def sum_collected_for_manager(
        self, db: AsyncSession, manager_id: uuid.UUID, start: datetime, end: datetime
    ) -> Decimal:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(func.sum(Payment.amount))
            .join(Contract, Contract.id == Payment.contract_id)
            .where(
                Contract.property_id.in_(owned_property_ids),
                Payment.status == PaymentStatus.PAID,
                Payment.paid_at.between(start, end),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one() or Decimal("0")

    async def get_recent(self, db: AsyncSession, limit: int = 10) -> Sequence[Payment]:
        limit = min(max(0, limit), 100)
        stmt = select(Payment).order_by(Payment.paid_at.desc(), Payment.id).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_recent_for_manager(
        self, db: AsyncSession, manager_id: uuid.UUID, limit: int = 10
    ) -> Sequence[Payment]:
        limit = min(max(0, limit), 100)
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(Payment)
            .join(Contract, Contract.id == Payment.contract_id)
            .where(Contract.property_id.in_(owned_property_ids))
            .order_by(Payment.paid_at.desc(), Payment.id)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()


# Instantiate once — import this instance everywhere
payment_repo = PaymentRepository(Payment)
