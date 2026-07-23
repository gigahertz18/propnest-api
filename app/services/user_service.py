from collections.abc import Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from uuid import UUID

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.services.exceptions import (
    UserNotFoundError,
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
    ManagerAssignedToPropertyError,
)
from app.repositories.user import UserRepository


class UserService:
    """
    Business logic around `User` entities.

    This service wraps the repository and raises domain-specific
    exceptions where appropriate so the route layer can translate
    them into HTTP responses.
    """

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def list_users(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[User]:
        return await self.user_repo.get_all(db, skip=skip, limit=limit)

    async def get_user(self, db: AsyncSession, id: UUID) -> User:
        user = await self.user_repo.get_by_id(db, id)
        if not user:
            raise UserNotFoundError("User not found")
        return user

    async def create_user(self, db: AsyncSession, payload: UserCreate) -> User:
        # Pre-check to provide fast feedback in the common case
        if await self.user_repo.get_by_email(db, payload.email):
            raise EmailAlreadyExistsError("A user with this email already exists")
        if await self.user_repo.get_by_username(db, payload.username):
            raise UsernameAlreadyExistsError("A user with this username already exists")

        # Create may still fail under concurrent requests due to DB unique
        # constraints. Translate IntegrityError into domain exceptions.
        try:
            user = await self.user_repo.create(db, payload)
            await db.commit()
            return user
        except IntegrityError as e:
            # Inspect DB driver's error message to determine which unique
            # constraint was violated. This is defensive and intentionally
            # tolerant across DB drivers.
            msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
            if "email" in msg or "users_email" in msg or "users_email_key" in msg:
                raise EmailAlreadyExistsError("A user with this email already exists")
            if "username" in msg or "users_username" in msg or "users_username_key" in msg:
                raise UsernameAlreadyExistsError("A user with this username already exists")
            # Unknown integrity problem — re-raise as a generic username/email
            # collision to avoid leaking DB details to route layer.
            raise EmailAlreadyExistsError("A user with this email or username already exists")

    async def update_user(self, db: AsyncSession, id: UUID, payload: UserUpdate) -> User:
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
            msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
            if "email" in msg or "users_email" in msg:
                raise EmailAlreadyExistsError("A user with this email already exists")
            if "username" in msg or "users_username" in msg:
                raise UsernameAlreadyExistsError("A user with this username already exists")
            raise

        if not user:
            raise UserNotFoundError("User not found")
        await db.commit()
        return user

    async def delete_user(self, db: AsyncSession, id: UUID) -> User:
        user = await self.user_repo.delete(db, id)

        if not user:
            raise UserNotFoundError("User not found")

        try:
            await db.commit()
        except IntegrityError as e:
            raise ManagerAssignedToPropertyError(
                f"User {id} cannot be deleted because they are still assigned as manager " "on one or more properties."
            ) from e
        return user
