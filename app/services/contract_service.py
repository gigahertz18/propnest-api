from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.repositories.contract import ContractRepository
from app.schemas.contract import ContractCreate, ContractUpdate
from app.models.contract import Contract, RentalType
from app.services.exceptions import ContractActiveError


class ContractService:
    """Business logic for rental `Contract` entities."""

    def __init__(self, contract_repo: ContractRepository) -> None:
        self.contract_repo = contract_repo

    def list_contracts(self, db: Session, skip: int = 0, limit: int = 100) -> list[Contract]:
        return self.contract_repo.get_all(db, skip=skip, limit=limit)

    def get_contract(self, db: Session, id: UUID) -> Contract | None:
        return self.contract_repo.get_by_id(db, id)

    def create_contract(self, db: Session, payload: ContractCreate) -> Contract:
        # Rely on DB constraint to prevent race conditions where two concurrent
        # requests attempt to create an ACTIVE contract for the same property.
        # Attempt the insert and translate unique/constraint errors into the
        # domain-specific `ContractActiveError` so callers get a consistent
        # response without depending on a fragile pre-check.
        try:
            return self.contract_repo.create(db, payload)
        except IntegrityError as e:
            msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
            if "uq_active_contract_property" in msg or ("duplicate key value" in msg and "property_id" in msg):
                raise ContractActiveError("An active contract already exists for this property")
            raise

    def update_contract(self, db: Session, id: UUID, payload: ContractUpdate) -> Contract | None:
        return self.contract_repo.update(db, id, payload)

    def delete_contract(self, db: Session, id: UUID) -> Contract | None:
        return self.contract_repo.delete(db, id)

    def get_by_property(self, db: Session, property_id: UUID) -> list[Contract]:
        return self.contract_repo.get_by_property(db, property_id)

    def get_active_contract_by_property(self, db: Session, property_id: UUID) -> Contract | None:
        return self.contract_repo.get_active_contract_by_property(db, property_id)

    def get_by_tenant(self, db: Session, tenant_id: UUID) -> list[Contract]:
        return self.contract_repo.get_by_tenant(db, tenant_id)

    def get_by_status(self, db: Session, status: str) -> list[Contract]:
        return self.contract_repo.get_by_status(db, status)

    def get_by_rental_type(self, db: Session, rental_type: RentalType) -> list[Contract]:
        return self.contract_repo.get_by_rental_type(db, rental_type)

    def get_by_booking_source(self, db: Session, booking_source: str) -> list[Contract]:
        return self.contract_repo.get_by_booking_source(db, booking_source)
