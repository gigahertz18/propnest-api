import uuid

from collections.abc import Sequence
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repositories.base import BaseRepository
from app.models.receipt import Receipt
from app.models.payment import Payment
from app.leasing.models.contract import Contract
from app.properties.models.property import Property


class ReceiptRepository(BaseRepository[Receipt, dict, None]):
    """
    Receipt-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create are inherited — Receipts are append-only, so
    `update`/`delete` are never called for this model.
    """

    async def get_by_payment(
        self,
        db: AsyncSession,
        payment_id: uuid.UUID,
    ) -> Sequence[Receipt]:
        """Return every receipt ever issued for a payment (original + reprints), oldest first."""
        return await self._all(db, self.model.payment_id == payment_id, order_by=self.model.created_at)

    async def next_receipt_number(self, db: AsyncSession) -> int:
        """Atomically allocate the next value from the Identity-backed sequence.

        Needed because the receipt number must appear on the PDF before the
        Receipt row can be inserted (Receipt.document_id is NOT NULL + unique,
        so the Document must exist first) — this pulls the same sequence the
        column's Identity would otherwise advance on insert.
        """
        result = await db.execute(select(func.nextval(func.pg_get_serial_sequence("receipts", "receipt_number"))))
        return result.scalar_one()

    async def get_all_for_manager(
        self,
        db: AsyncSession,
        manager_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Receipt]:
        """Receipts a manager may see — those whose payment's contract belongs
        to one of their own properties (mirrors PaymentRepository.get_all_for_manager)."""
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(Receipt)
            .join(Payment, Payment.id == Receipt.payment_id)
            .join(Contract, Contract.id == Payment.contract_id)
            .where(Contract.property_id.in_(owned_property_ids))
            .order_by(Receipt.created_at, Receipt.id)
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
            .select_from(Receipt)
            .join(Payment, Payment.id == Receipt.payment_id)
            .join(Contract, Contract.id == Payment.contract_id)
            .where(Contract.property_id.in_(owned_property_ids))
        )
        result = await db.execute(stmt)
        return int(result.scalar_one())


# Instantiate once — import this instance everywhere
receipt_repo = ReceiptRepository(Receipt)
