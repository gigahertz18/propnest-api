import uuid
from sqlalchemy.orm import Session

from app.repositories.base import BaseRepository
from app.models.contract import Contract, RentalType
from app.schemas.contract import ContractCreate, ContractUpdate


class ContractRepository(BaseRepository[Contract, ContractCreate, ContractUpdate]):
    """
    Contract-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    def get_by_property(
        self,
        db: Session,
        property_id: uuid.UUID,
    ) -> list[Contract]:
        """Return all contracts linked to a given property."""
        return (
            db.query(self.model)
            .filter(self.model.property_id == property_id)
            .all()
        )

    def get_by_tenant(
        self,
        db: Session,
        tenant_id: uuid.UUID,
    ) -> list[Contract]:
        """Return all contracts linked to a given tenant."""
        return (
            db.query(self.model)
            .filter(self.model.tenant_id == tenant_id)
            .all()
        )

    def get_by_status(
        self,
        db: Session,
        status: str,
    ) -> list[Contract]:
        """Return all contracts with a given status (e.g. ACTIVE, EXPIRED)."""
        return (
            db.query(self.model)
            .filter(self.model.status == status)
            .all()
        )

    def get_by_rental_type(
        self,
        db: Session,
        rental_type: RentalType,
    ) -> list[Contract]:
        """Return all contracts of a given rental type."""
        return (
            db.query(self.model)
            .filter(self.model.rental_type == rental_type)
            .all()
        )

    def get_by_booking_source(
        self,
        db: Session,
        booking_source: str,
    ) -> list[Contract]:
        """Return all contracts originating from a given booking source."""
        return (
            db.query(self.model)
            .filter(self.model.booking_source == booking_source)
            .all()
        )

    def get_active_contract_by_property(
        self,
        db: Session,
        property_id: uuid.UUID,
    ) -> Contract | None:
        """
        Return the single active contract for a property, if one exists.
        Useful for checking occupancy before creating a new contract.
        """
        return (
            db.query(self.model)
            .filter(
                self.model.property_id == property_id,
                self.model.status == "ACTIVE",
            )
            .first()
        )


# Instantiate once — import this instance everywhere
contract_repo = ContractRepository(Contract)
