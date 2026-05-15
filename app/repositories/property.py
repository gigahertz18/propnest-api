from sqlalchemy.orm import Session
from app.repositories.base import BaseRepository
from app.models.property import Property, PropertyStatus
from app.schemas.property import PropertyCreate, PropertyUpdate


class PropertyRepository(BaseRepository[Property, PropertyCreate, PropertyUpdate]):
    """
    Property-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    def get_by_status(
        self,
        db: Session,
        status: PropertyStatus,
    ) -> list[Property]:
        return db.query(self.model).filter(self.model.status == status).all()


# Instantiate once — import this instance everywhere
property_repo = PropertyRepository(Property)
