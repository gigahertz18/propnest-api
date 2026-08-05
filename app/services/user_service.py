from collections.abc import Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from uuid import UUID

from app.models.user import User, UserRole
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.services.utils import integrity_error_message
from app.services.exceptions import (
    UserNotFoundError,
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
    ManagerAssignedToPropertyError,
    UserForbiddenError,
)


class UserService:
    """
    Business logic around `User` entities.

    This service wraps the repository and raises domain-specific
    exceptions where appropriate so the route layer can translate
    them into HTTP responses.
    """

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def list_users(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[User]:
        self._require_admin(current_user)
        return await self.user_repo.get_all(db, skip=skip, limit=limit)

    async def get_user(self, db: AsyncSession, id: UUID, current_user: User) -> User:
        self._authorize_self_or_admin(current_user, id)
        user = await self.user_repo.get_by_id(db, id)
        if not user:
            raise UserNotFoundError("User not found")
        return user

    async def create_user(self, db: AsyncSession, payload: UserCreate) -> User:
        # No self-or-admin check needed: this creates a brand-new account,
        # so there's no existing resource to own. Admin-only role gating
        # at the route layer (require_admin) is sufficient here — there's
        # no per-resource ownership dimension the way get/update/delete have.
        # Pre-check for fast feedback in the common case
        if await self.user_repo.get_by_email(db, payload.email):
            raise EmailAlreadyExistsError("A user with this email already exists")
        if await self.user_repo.get_by_username(db, payload.username):
            raise UsernameAlreadyExistsError("A user with this username already exists")

        # Concurrent requests can still race past the pre-check - translate
        # the resulting IntegrityError into a domain exception
        try:
            user = await self.user_repo.create(db, payload)
            await db.commit()
            return user
        except IntegrityError as e:
            self._raise_conflict(
                e, default=EmailAlreadyExistsError("A user with this email or username already exists")
            )

    async def update_user(self, db: AsyncSession, id: UUID, payload: UserUpdate, current_user: User) -> User:
        self._authorize_self_or_admin(current_user, id)

        if payload.role is not None and getattr(current_user, "role", None) != UserRole.ADMIN:
            raise UserForbiddenError("You cannot change your own role.")

        if payload.email is not None:
            existing = await self.user_repo.get_by_email(db, payload.email)
            if existing and existing.id != id:
                raise EmailAlreadyExistsError("A user with this email already exists")

        if payload.username is not None:
            existing = await self.user_repo.get_by_username(db, payload.username)
            if existing and existing.id != id:
                raise UsernameAlreadyExistsError("A user with this username already exists")

        try:
            user = await self.user_repo.update(db, id, payload)
        except IntegrityError as e:
            self._raise_conflict(e)

        if not user:
            raise UserNotFoundError("User not found")
        await db.commit()
        return user

    async def delete_user(self, db: AsyncSession, id: UUID, current_user: User) -> User:
        self._require_admin(current_user)

        if current_user.id == id:
            raise UserForbiddenError("You cannot delete your own account.")

        user = await self.user_repo.delete(db, id)

        if not user:
            raise UserNotFoundError("User not found")

        try:
            await db.commit()
        except IntegrityError as e:
            raise ManagerAssignedToPropertyError(
                f"User {id} cannot be deleted because they are still assigned as manager on one or more properties."
            ) from e
        return user

    @staticmethod
    def _require_admin(current_user: User) -> None:
        if getattr(current_user, "role", None) != UserRole.ADMIN:
            raise UserForbiddenError("Admin access required.")

    @staticmethod
    def _authorize_self_or_admin(current_user: User, target_id: UUID) -> None:
        role = getattr(current_user, "role", None)
        if role != UserRole.ADMIN and getattr(current_user, "id", None) != target_id:
            raise UserForbiddenError("You can only access your own profile.")

    @staticmethod
    def _raise_conflict(e: IntegrityError, default: Exception | None = None) -> None:
        """
        Translate an email/username unique-constraint violation into the matching domain exception.
        `default`, if given, is raised for an unrecognized constraint instead of re-raising `e`.
        """
        msg = integrity_error_message(e)
        if "email" in msg:
            raise EmailAlreadyExistsError("A user with this email already exists") from e
        if "username" in msg:
            raise UsernameAlreadyExistsError("A user with this username already exists") from e
        if default:
            raise default from e
        raise
