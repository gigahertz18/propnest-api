import uuid

from collections.abc import Sequence
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repositories.base import BaseRepository
from app.models.collection import Collection
from app.properties.models.property import Property
from app.schemas.collection import CollectionCreate, CollectionUpdate


class CollectionRepository(BaseRepository[Collection, CollectionCreate, CollectionUpdate]):
    """
    Collection-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    async def get_by_property(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Sequence[Collection]:
        """Return all collections linked to a given property."""
        return await self._all(db, self.model.property_id == property_id)

    async def get_by_contract(
        self,
        db: AsyncSession,
        contract_id: uuid.UUID,
    ) -> Sequence[Collection]:
        """Return all collections linked to a given contract."""
        return await self._all(db, self.model.contract_id == contract_id)

    async def count_all(self, db: AsyncSession) -> int:
        return await self._count(db)

    async def get_all_for_manager(
        self,
        db: AsyncSession,
        manager_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Collection]:
        """Collections a manager may see — those on properties they own."""
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(Collection)
            .where(Collection.property_id.in_(owned_property_ids))
            .order_by(Collection.created_at, Collection.id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_all_for_manager(self, db: AsyncSession, manager_id: uuid.UUID) -> int:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = select(func.count()).select_from(Collection).where(Collection.property_id.in_(owned_property_ids))
        result = await db.execute(stmt)
        return int(result.scalar_one())


# Instantiate once — import this instance everywhere
collection_repo = CollectionRepository(Collection)
