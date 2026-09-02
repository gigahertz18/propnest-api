import uuid

from datetime import date

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repositories.base import BaseRepository
from app.leasing.models.contract import Contract
from app.leasing.models.lease import Lease, LeaseStatus
from app.properties.models.property import Property
from app.leasing.schemas.lease import LeaseCreate, LeaseUpdate


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

    async def get_expiring(self, db: AsyncSession, start: date, end: date) -> list[Lease]:
        """Active leases whose end_date falls within [start, end]."""
        stmt = select(Lease).where(
            Lease.status == LeaseStatus.ACTIVE,
            Lease.end_date.is_not(None),
            Lease.end_date.between(start, end),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_expiring_for_manager(
        self, db: AsyncSession, manager_id: uuid.UUID, start: date, end: date
    ) -> list[Lease]:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)
        owned_contract_ids = select(Contract.id).where(Contract.property_id.in_(owned_property_ids))

        stmt = select(Lease).where(
            Lease.contract_id.in_(owned_contract_ids),
            Lease.status == LeaseStatus.ACTIVE,
            Lease.end_date.is_not(None),
            Lease.end_date.between(start, end),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self, db: AsyncSession) -> list[Lease]:
        """
        Every ACTIVE lease, portfolio-wide, unpaginated.

        Deliberately bypass get_all()'s 100-row pagination cap - this backs
        the billing scheduler job , which must consider every active lease each run,
        not just the first page. Not manager-scoped: the job runs as the system
        identity, which is authorized portfolio-wide.
        """

        return list(await self._all(db, self.model.status == LeaseStatus.ACTIVE))


# Instantiate once — import this instance everywhere
lease_repo = LeaseRepository(Lease)
