from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.repositories.property import PropertyRepository
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.models.property import Property, PropertyStatus
from app.services.exceptions import RelatedResourceNotFoundError, PropertyAlreadyExistsError


class PropertyService:
    """Thin business layer for `Property` operations."""

    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def list_properties(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Property]:
        return await self.property_repo.get_all(db, skip=skip, limit=limit)

    async def get_property(self, db: AsyncSession, prop_id: UUID) -> Property | None:
        prop = await self.property_repo.get_by_id(db, prop_id)
        if not prop:
            raise RelatedResourceNotFoundError(f"Property {prop_id} not found.")
        return prop

    async def create_property(self, db: AsyncSession, payload: PropertyCreate) -> Property:
        try:
            prop = await self.property_repo.create(db, payload)
            await db.commit()
            return prop
        except IntegrityError as e:
            msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
            if "uq_property_name_address" in msg:
                raise PropertyAlreadyExistsError(
                    f"A property named '{payload.name}' at '{payload.address}' already exists."
                )
            raise

    async def update_property(self, db: AsyncSession, prop_id: UUID, payload: PropertyUpdate) -> Property | None:
        await self.get_property(db, prop_id)
        try:
            prop = await self.property_repo.update(db, prop_id, payload)
            await db.commit()
            return prop
        except IntegrityError as e:
            msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
            if "uq_property_name_address" in msg:
                raise PropertyAlreadyExistsError("A property with this name and address already exists.")
            raise

    async def delete_property(self, db: AsyncSession, prop_id: UUID) -> Property | None:
        await self.get_property(db, prop_id)
        prop = await self.property_repo.delete(db, prop_id)
        await db.commit()
        return prop

    async def get_by_status(self, db: AsyncSession, status: PropertyStatus) -> list[Property]:
        return await self.property_repo.get_by_status(db, status)
