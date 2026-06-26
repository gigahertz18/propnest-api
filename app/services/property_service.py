from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.property import PropertyRepository
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.models.property import Property, PropertyStatus


class PropertyService:
    """Thin business layer for `Property` operations."""

    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def list_properties(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Property]:
        return await self.property_repo.get_all(db, skip=skip, limit=limit)

    async def get_property(self, db: AsyncSession, id: UUID) -> Property | None:
        return await self.property_repo.get_by_id(db, id)

    async def create_property(self, db: AsyncSession, payload: PropertyCreate) -> Property:
        prop = await self.property_repo.create(db, payload)
        await db.commit()
        return prop

    async def update_property(self, db: AsyncSession, id: UUID, payload: PropertyUpdate) -> Property | None:
        prop = await self.property_repo.update(db, id, payload)
        await db.commit()
        return prop

    async def delete_property(self, db: AsyncSession, id: UUID) -> Property | None:
        prop = await self.property_repo.delete(db, id)
        await db.commit()
        return prop

    async def get_by_status(self, db: AsyncSession, status: PropertyStatus) -> list[Property]:
        return await self.property_repo.get_by_status(db, status)
