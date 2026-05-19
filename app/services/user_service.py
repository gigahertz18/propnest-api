from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.models.user import User
from app.services.exceptions import (
    UserNotFoundError,
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
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

    def list_users(self, db: Session, skip: int = 0, limit: int = 100) -> list[User]:
        return self.user_repo.get_all(db, skip=skip, limit=limit)

    def get_user(self, db: Session, id: UUID) -> User:
        user = self.user_repo.get_by_id(db, id)
        if not user:
            raise UserNotFoundError("User not found")
        return user

    def create_user(self, db: Session, payload: UserCreate) -> User:
        # Pre-check to provide fast feedback in the common case
        if self.user_repo.get_by_email(db, payload.email):
            raise EmailAlreadyExistsError("A user with this email already exists")
        if self.user_repo.get_by_username(db, payload.username):
            raise UsernameAlreadyExistsError("A user with this username already exists")

        # Create may still fail under concurrent requests due to DB unique
        # constraints. Translate IntegrityError into domain exceptions.
        try:
            return self.user_repo.create(db, payload)
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

    def update_user(self, db: Session, id: UUID, payload: UserUpdate) -> User:
        if payload.email is not None:
            existing = self.user_repo.get_by_email(db, payload.email)
            if existing and existing.id != id:
                raise EmailAlreadyExistsError("A user with this email already exists")

        if payload.username is not None:
            existing = self.user_repo.get_by_username(db, payload.username)
            if existing and existing.id != id:
                raise UsernameAlreadyExistsError("A user with this username already exists")

        try:
            user = self.user_repo.update(db, id, payload)
        except IntegrityError as e:
            msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
            if "email" in msg or "users_email" in msg:
                raise EmailAlreadyExistsError("A user with this email already exists")
            if "username" in msg or "users_username" in msg:
                raise UsernameAlreadyExistsError("A user with this username already exists")
            raise

        if not user:
            raise UserNotFoundError("User not found")
        return user

    def delete_user(self, db: Session, id: UUID) -> User:
        user = self.user_repo.delete(db, id)
        if not user:
            raise UserNotFoundError("User not found")
        return user
