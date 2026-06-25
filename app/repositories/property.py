from sqlalchemy import select
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
        
        statement = select(self.model).where(self.model.status == status)
        result = await db.execute(statement)
        return result.scalars().all()

# Instantiate once — import this instance everywhere
property_repo = PropertyRepository(Property)
