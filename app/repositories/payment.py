import uuid

from collections.abc import Sequence
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.payment import Payment
from app.models.contract import Contract
from app.models.property import Property
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
            .order_by(Payment.created_at)
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


# Instantiate once — import this instance everywhere
payment_repo = PaymentRepository(Payment)
