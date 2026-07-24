from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.repositories.property import PropertyRepository
from app.repositories.user import UserRepository
from app.schemas.base import PaginatedResponse
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.models.property import Property, PropertyStatus
from app.models.user import User, UserRole
from app.services.base import ResourceAuthorizationMixin
from app.services.utils import integrity_error_message
from app.services.exceptions import (
    PropertyAlreadyExistsError,
    PropertyForbiddenError,
    PropertyManagerAssignmentError,
    PropertyInUseError,
    RelatedResourceNotFoundError,
    UserNotFoundError,
)


class PropertyService(ResourceAuthorizationMixin):
    """Thin business layer for `Property` operations."""

    def __init__(self, property_repo: PropertyRepository, user_repo: UserRepository | None = None) -> None:
        self.property_repo = property_repo
        self.user_repo = user_repo

    async def list_properties(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[Property]:
        """Admins see every property; managers only see their own."""
        return await self._list_scoped_by_manager(db, current_user, self.property_repo, skip, limit)

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
            if "uq_property_name_address" in integrity_error_message(e):
                raise PropertyAlreadyExistsError(
                    f"A property named '{payload.name}' at '{payload.address}' already exists."
                )
            raise

    async def update_property(
        self, db: AsyncSession, prop_id: UUID, payload: PropertyUpdate, current_user: User
    ) -> Property:
        """Update/delete are admin-only at the route layer for now, so this
        always bypasses in practice - kept explicit so the code stays
        correct if that route requirement is ever loosened"""
        await self.get_property(db, prop_id, current_user=current_user)
        try:
            prop = await self.property_repo.update(db, prop_id, payload)
            await db.commit()
            return prop
        except IntegrityError as e:
            if "uq_property_name_address" in integrity_error_message(e):
                raise PropertyAlreadyExistsError("A property with this name and address already exists.")
            raise

    async def delete_property(self, db: AsyncSession, prop_id: UUID, current_user: User) -> Property:
        await self.get_property(db, prop_id, current_user=current_user)
        try:
            prop = await self.property_repo.delete(db, prop_id)
            await db.commit()
            return prop
        except IntegrityError as e:
            raise PropertyInUseError(
                f"Property {prop_id} cannot be deleted because it is still referenced by an "
                "existing contract or document."
            ) from e

    async def assign_manager(
        self,
        db: AsyncSession,
        prop_id: UUID,
        manager_id: UUID,
        current_user: User,
    ) -> Property:
        """
        Assign a manager to a property. Admin-only at the route layer.
        The only path that populates `Property.manager_id` outside of
        direct DB writes in tests — every manager-scoped authorization
        check in the app depends on this field being set through here.
        No unassign path: reassigning overwrites the current manager_id.
        There is no unassign path: reassigning simply overwrites the
        current `manager_id` rather than clearing it in between contracts.

        Raises:
            RelatedResourceNotFoundError: `prop_id` doesn't exist.
            UserNotFoundError: `manager_id` doesn't reference an existing user.
            PropertyManagerAssignmentError: the referenced user isn't a MANAGER.
        """
        if self.user_repo is None:
            raise RuntimeError(f"{type(self).__name__}.assign_manager requires user_repo to be injected.")

        prop = await self.get_property(db, prop_id, current_user=current_user)

        manager = await self.user_repo.get_by_id(db, manager_id)
        if not manager:
            raise UserNotFoundError(f"User {manager_id} not found.")
        if manager.role != UserRole.MANAGER:
            raise PropertyManagerAssignmentError(f"User {manager_id} does not have the manager role.")

        prop = await self.property_repo.update(db, prop_id, {"manager_id": manager_id})
        await db.commit()
        return prop

    async def get_by_status(self, db: AsyncSession, status: PropertyStatus) -> Sequence[Property]:
        return await self.property_repo.get_by_status(db, status)
