from sqlalchemy.orm import Session
from app.repositories.base import BaseRepository
from app.models.property import Property, RentalType, PropertyStatus
from app.schemas.property import PropertyCreate, PropertyUpdate


class PropertyRepository(BaseRepository[Property, PropertyCreate, PropertyUpdate]):
    """
    Property-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    def get_by_rental_type(
        self,
        db: Session,
        rental_type: RentalType,
    ) -> list[Property]:
        return db.query(self.model).filter(self.model.rental_type == rental_type).all()

    def get_by_status(
        self,
        db: Session,
        status: PropertyStatus,
    ) -> list[Property]:
        return db.query(self.model).filter(self.model.status == status).all()

    def get_by_platform(
        self,
        db: Session,
        listing_platform: str,
    ) -> list[Property]:
        return db.query(self.model).filter(self.model.listing_platform == listing_platform).all()


# Instantiate once — import this instance everywhere
property_repo = PropertyRepository(Property)
