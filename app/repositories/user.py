from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.repositories.base import BaseRepository
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate
from uuid import UUID


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
        return db.query(self.model).filter(self.model.username == username).first()

    def get_by_email(
        self,
        db: Session,
        email: str,
    ) -> User | None:
        return db.query(self.model).filter(self.model.email == email).first()

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

        if "@" in identifier:
            return self.get_by_email(db, identifier)
        else:
            return self.get_by_username(db, identifier)
    
    def create(self, db: Session, payload: UserCreate) -> User:
        """Override create to handle password hashing."""

        # Hash the password before creating the user
        
        data = payload.model_dump(exclude={"password"})
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
            
        for field, value in updates.items():
            setattr(obj, field, value)
            
        db.commit()
        db.refresh(obj) 
        return obj

# Instantiate once — import this instance everywhere
user_repo = UserRepository(User)
