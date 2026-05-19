from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.property import PropertyRepository
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.models.property import Property, PropertyStatus


class PropertyService:
    """Thin business layer for `Property` operations."""

    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    def list_properties(self, db: Session, skip: int = 0, limit: int = 100) -> list[Property]:
        return self.property_repo.get_all(db, skip=skip, limit=limit)

    def get_property(self, db: Session, id: UUID) -> Property | None:
        return self.property_repo.get_by_id(db, id)

    def create_property(self, db: Session, payload: PropertyCreate) -> Property:
        return self.property_repo.create(db, payload)

    def update_property(self, db: Session, id: UUID, payload: PropertyUpdate) -> Property | None:
        return self.property_repo.update(db, id, payload)

    def delete_property(self, db: Session, id: UUID) -> Property | None:
        return self.property_repo.delete(db, id)

    def get_by_status(self, db: Session, status: PropertyStatus) -> list[Property]:
        return self.property_repo.get_by_status(db, status)
