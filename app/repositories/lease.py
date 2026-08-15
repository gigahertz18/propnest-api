import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.contract import Contract
from app.models.lease import Lease
from app.models.property import Property
from app.schemas.lease import LeaseCreate, LeaseUpdate


class LeaseRepository(BaseRepository[Lease, LeaseCreate, LeaseUpdate]):
    """
    Lease-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    async def get_by_contract(
        self,
        db: AsyncSession,
        contract_id: uuid.UUID,
    ) -> Lease | None:
        """Return the single lease for a contract (1:1), if one exists."""
        return await self._first(db, self.model.contract_id == contract_id)

    async def count_all(self, db: AsyncSession) -> int:
        return await self._count(db)

    async def get_all_for_manager(
        self,
        db: AsyncSession,
        manager_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Lease]:
        """Leases a manager may see — those on contracts for properties they own."""
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)
        owned_contract_ids = select(Contract.id).where(Contract.property_id.in_(owned_property_ids))

        stmt = (
            select(Lease)
            .where(Lease.contract_id.in_(owned_contract_ids))
            .order_by(Lease.created_at, Lease.id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_all_for_manager(self, db: AsyncSession, manager_id: uuid.UUID) -> int:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)
        owned_contract_ids = select(Contract.id).where(Contract.property_id.in_(owned_property_ids))

        stmt = select(func.count()).select_from(Lease).where(Lease.contract_id.in_(owned_contract_ids))
        result = await db.execute(stmt)
        return int(result.scalar_one())


# Instantiate once — import this instance everywhere
lease_repo = LeaseRepository(Lease)
