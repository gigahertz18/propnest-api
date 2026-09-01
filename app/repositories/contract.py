import uuid

from collections.abc import Sequence
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repositories.base import BaseRepository
from app.models.contract import Contract, RentalType
from app.models.property import Property
from app.schemas.contract import ContractCreate, ContractUpdate


class ContractRepository(BaseRepository[Contract, ContractCreate, ContractUpdate]):
    """
    Contract-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    async def get_by_property(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Sequence[Contract]:
        """Return all contracts linked to a given property."""

        return await self._all(db, self.model.property_id == property_id)

    async def get_by_tenant(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> Sequence[Contract]:
        """Return all contracts linked to a given tenant."""
        return await self._all(db, self.model.tenant_id == tenant_id)

    async def get_by_status(
        self,
        db: AsyncSession,
        status: str,
    ) -> Sequence[Contract]:
        """Return all contracts with a given status (e.g. ACTIVE, EXPIRED)."""

        return await self._all(db, self.model.status == status)

    async def get_by_rental_type(
        self,
        db: AsyncSession,
        rental_type: RentalType,
    ) -> Sequence[Contract]:
        """Return all contracts of a given rental type."""

        return await self._all(db, self.model.rental_type == rental_type)

    async def get_by_booking_source(
        self,
        db: AsyncSession,
        booking_source: str,
    ) -> Sequence[Contract]:
        """Return all contracts originating from a given booking source."""

        return await self._all(db, self.model.booking_source == booking_source)

    async def count_all(self, db: AsyncSession) -> int:
        return await self._count(db)

    async def get_all_for_manager(
        self,
        db: AsyncSession,
        manager_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Contract]:
        """Contracts a manager may see — those on properties they own."""
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(Contract)
            .where(Contract.property_id.in_(owned_property_ids))
            .order_by(Contract.created_at, Contract.id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_all_for_manager(self, db: AsyncSession, manager_id: uuid.UUID) -> int:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = select(func.count()).select_from(Contract).where(Contract.property_id.in_(owned_property_ids))
        result = await db.execute(stmt)
        return int(result.scalar_one())

    async def get_active_contract_by_property(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Contract | None:
        """
        Return the single active contract for a property, if one exists.
        Useful for checking occupancy before creating a new contract.
        """

        return await self._first(db, self.model.property_id == property_id, self.model.status == "ACTIVE")


# Instantiate once — import this instance everywhere
contract_repo = ContractRepository(Contract)
