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
        """
        Fails closed: only ADMIN (bypass) and MANAGER (must own the property) are authorized. Any other role -
        including a plain USER - is rejected outright rather than failing through as if authorized,
        matching the fail-closed pattern used by `ResourceAuthorizationMixin._authorize_user_to_property` and
        `_list_scoped_by_manager` elsewhere in the service layer.
        """

        prop = await self.property_repo.get_by_id(db, prop_id)
        if not prop:
            raise RelatedResourceNotFoundError(f"Property {prop_id} not found.")

        role = getattr(current_user, "role", None)
        is_admin = role == UserRole.ADMIN
        is_owning_manager = role == UserRole.MANAGER and current_user.id == prop.manager_id

        if not (is_admin or is_owning_manager):
            raise PropertyForbiddenError(f"Property {prop.id} is not accessible for this user")

        return prop

    async def create_property(self, db: AsyncSession, payload: PropertyCreate, current_user: User) -> Property:
        if getattr(current_user, "role", None) != UserRole.ADMIN:
            raise PropertyForbiddenError("Only admins may create properties.")
        try:
            prop = await self.property_repo.create(db, payload)
            await db.commit()
            return prop
        except IntegrityError as e:
            self._raise_if_name_address_conflict(e, f"A property named '{payload.name}' at '{payload.address}'")

    async def update_property(
        self, db: AsyncSession, prop_id: UUID, payload: PropertyUpdate, current_user: User
    ) -> Property:
        """Update/delete are admin-only at the route layer, so the ownership check below
        always passes in practice - kept explicit so this stays correct if the route
        requirement is ever loosened.
        """
        await self.get_property(db, prop_id, current_user=current_user)
        try:
            prop = await self.property_repo.update(db, prop_id, payload)
            await db.commit()
            return prop
        except IntegrityError as e:
            self._raise_if_name_address_conflict(e, "A property with this name and address already exists.")

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
        Also enforced here: only admins may reassign a property's manager
        — a manager who owns the property must not be able to do this
        just because `get_property`'s ownership check would let them
        through for a read.
        The only path that populates `Property.manager_id` outside of
        direct DB writes in tests — every manager-scoped authorization
        check in the app depends on this field being set through here.
        No unassign path: reassigning overwrites the current manager_id
        rather than clearing it first.

        Raises:
            RelatedResourceNotFoundError: `prop_id` doesn't exist.
            PropertyForbiddenError: the `current user` isn't an admin.
            UserNotFoundError: `manager_id` doesn't reference an existing user.
            PropertyManagerAssignmentError: the referenced user isn't a MANAGER.
        """
        if self.user_repo is None:
            raise RuntimeError(f"{type(self).__name__}.assign_manager requires user_repo to be injected.")

        if current_user.role != UserRole.ADMIN:
            raise PropertyForbiddenError("Only admins may assign managers to properties.")

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

    @staticmethod
    def _raise_if_name_address_conflict(e: IntegrityError, subject: str) -> None:
        """Translate a `uq_property_name_address` violation into `PropertyAlreadyExistsError`;
        re-raises unrelated IntegrityErrors."""
        if "uq_property_name_address" in integrity_error_message(e):
            raise PropertyAlreadyExistsError(f"{subject} already exists.") from e
        raise e
