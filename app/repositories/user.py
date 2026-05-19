from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.repositories.base import BaseRepository
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate
from uuid import UUID


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_username(username: str) -> str:
    return username.strip().lower()


class UserRepository(BaseRepository[User, UserCreate, UserUpdate]):
    """
    User-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    def get_by_username(
        self,
        db: Session,
        username: str,
    ) -> User | None:
        normalized = _normalize_username(username)
        return db.query(self.model).filter(self.model.username == normalized).first()

    def get_by_email(
        self,
        db: Session,
        email: str,
    ) -> User | None:
        normalized = _normalize_email(email)
        return db.query(self.model).filter(self.model.email == normalized).first()

    def get_by_role(
        self,
        db: Session,
        role: UserRole,
    ) -> list[User]:
        return db.query(self.model).filter(self.model.role == role).all()

    def get_by_identifier(
        self,
        db: Session,
        identifier: str,
    ) -> User | None:
        """Get user by username or email."""
        if not identifier:
            return None

        identifier = identifier.strip()
        # If identifier contains '@', treat it strictly as an email.
        # Avoid passing an email string into the username lookup.
        if "@" in identifier:
            return self.get_by_email(db, identifier)
        return self.get_by_username(db, identifier)

    def create(self, db: Session, payload: UserCreate) -> User:
        """Override create to handle password hashing."""

        data = payload.model_dump(exclude={"password"})
        data["email"] = _normalize_email(data["email"])
        data["username"] = _normalize_username(data["username"])

        obj = self.model(**data, password_hash=hash_password(payload.password))

        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(self, db: Session, id: UUID, payload: UserUpdate) -> User | None:
        """Override update to handle password hashing if password is being updated."""

        obj = self.get_by_id(db, id)
        if not obj:
            return None

        updates = payload.model_dump(exclude_unset=True)

        if "password" in updates:
            updates["password_hash"] = hash_password(updates.pop("password"))

        if "email" in updates and updates["email"] is not None:
            updates["email"] = _normalize_email(updates["email"])

        if "username" in updates and updates["username"] is not None:
            updates["username"] = _normalize_username(updates["username"])

        for field, value in updates.items():
            setattr(obj, field, value)

        db.commit()
        db.refresh(obj)
        return obj


# Instantiate once — import this instance everywhere
user_repo = UserRepository(User)
