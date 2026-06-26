from sqlalchemy.ext.asyncio import AsyncSession
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
    ) -> list[Property]:

        return await self._all(db, self.model.status == status)


# Instantiate once — import this instance everywhere
property_repo = PropertyRepository(Property)
