from collections.abc import Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.repositories.base import BaseRepository
from app.models.property import Property, PropertyStatus
from app.schemas.property import PropertyCreate, PropertyUpdate


class PropertyRepository(BaseRepository[Property, PropertyCreate, PropertyUpdate]):
    """
    Property-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    async def get_by_status(
        self,
        db: AsyncSession,
        status: PropertyStatus,
    ) -> Sequence[Property]:

        return await self._all(db, self.model.status == status)

    async def get_all_for_manager(
        self,
        db: AsyncSession,
        manager_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Property]:

        return await self._all(
            db,
            self.model.manager_id == manager_id,
            skip=skip,
            limit=limit,
        )

    async def count_all(self, db: AsyncSession) -> int:
        return await self._count(db)

    async def count_all_for_manager(self, db: AsyncSession, manager_id: UUID) -> int:
        return await self._count(db, self.model.manager_id == manager_id)


# Instantiate once — import this instance everywhere
property_repo = PropertyRepository(Property)
