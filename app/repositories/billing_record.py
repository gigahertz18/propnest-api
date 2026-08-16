import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.billing_record import BillingRecord
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


# Instantiate once — import this instance everywhere
billing_record_repo = BillingRecordRepository(BillingRecord)
