from collections.abc import Sequence
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.repositories.property import PropertyRepository
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.models.property import Property, PropertyStatus
from app.models.user import User, UserRole
from app.services.exceptions import RelatedResourceNotFoundError, PropertyAlreadyExistsError, PropertyForbiddenError


class PropertyService:
    """Thin business layer for `Property` operations."""

    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def list_properties(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Property]:
        """`current_user` is required — see TenantService.list_tenants'
        docstring for why an optional, silently-skippable auth parameter
        is a footgun this codebase has already been bitten by once."""
        if current_user.role == UserRole.MANAGER:
            return await self.property_repo.get_all_for_manager(
                db,
                current_user.id,
                skip=skip,
                limit=limit,
            )
        return await self.property_repo.get_all(db, skip=skip, limit=limit)

    async def get_property(self, db: AsyncSession, prop_id: UUID, current_user: User) -> Property:
        prop = await self.property_repo.get_by_id(db, prop_id)
        if not prop:
            raise RelatedResourceNotFoundError(f"Property {prop_id} not found.")

        if current_user.role == UserRole.MANAGER and current_user.id != prop.manager_id:
            raise PropertyForbiddenError(f"Property {prop.id} is not accessible for this user")

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

    async def update_property(
        self, db: AsyncSession, prop_id: UUID, payload: PropertyUpdate, current_user: User
    ) -> Property:
        # Today update/delete are admin-only at the route layer, so this
        # check always bypasses in practice — but it's threaded through
        # explicitly so the code stays correct the moment that route
        # requirement is ever loosened to manager-or-above, rather than
        # silently allowing a manager to touch any property because
        # nobody remembered to wire this up at that point.
        await self.get_property(db, prop_id, current_user=current_user)
        try:
            prop = await self.property_repo.update(db, prop_id, payload)
            await db.commit()
            return prop
        except IntegrityError as e:
            msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
            if "uq_property_name_address" in msg:
                raise PropertyAlreadyExistsError("A property with this name and address already exists.")
            raise

    async def delete_property(self, db: AsyncSession, prop_id: UUID, current_user: User) -> Property:
        await self.get_property(db, prop_id, current_user=current_user)
        prop = await self.property_repo.delete(db, prop_id)
        await db.commit()
        return prop

    async def get_by_status(self, db: AsyncSession, status: PropertyStatus) -> Sequence[Property]:
        return await self.property_repo.get_by_status(db, status)
