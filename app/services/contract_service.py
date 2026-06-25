from uuid import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.contract import ContractRepository
from app.schemas.contract import ContractCreate, ContractUpdate
from app.models.contract import Contract, RentalType
from app.services.exceptions import ContractActiveError


class ContractService:
    """Business logic for rental `Contract` entities."""

    def __init__(self, contract_repo: ContractRepository) -> None:
        self.contract_repo = contract_repo

    async def list_contracts(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Contract]:
        return await self.contract_repo.get_all(db, skip=skip, limit=limit)

    async def get_contract(self, db: AsyncSession, id: UUID) -> Contract | None:
        return await self.contract_repo.get_by_id(db, id)

    async def create_contract(self, db: AsyncSession, payload: ContractCreate) -> Contract:
        # Rely on DB constraint to prevent race conditions where two concurrent
        # requests attempt to create an ACTIVE contract for the same property.
        # Attempt the insert and translate unique/constraint errors into the
        # domain-specific `ContractActiveError` so callers get a consistent
        # response without depending on a fragile pre-check.
        try:
            return await self.contract_repo.create(db, payload)
        except IntegrityError as e:
            msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
            if "uq_active_contract_property" in msg or ("duplicate key value" in msg and "property_id" in msg):
                raise ContractActiveError("An active contract already exists for this property")
            raise

    async def update_contract(self, db: AsyncSession, id: UUID, payload: ContractUpdate) -> Contract | None:
        return await self.contract_repo.update(db, id, payload)

    async def delete_contract(self, db: AsyncSession, id: UUID) -> Contract | None:
        return await self.contract_repo.delete(db, id)

    async def get_by_property(self, db: AsyncSession, property_id: UUID) -> list[Contract]:
        return await self.contract_repo.get_by_property(db, property_id)

    async def get_active_contract_by_property(self, db: AsyncSession, property_id: UUID) -> Contract | None:
        return await self.contract_repo.get_active_contract_by_property(db, property_id)

    async def get_by_tenant(self, db: AsyncSession, tenant_id: UUID) -> list[Contract]:
        return await self.contract_repo.get_by_tenant(db, tenant_id)

    async def get_by_status(self, db: AsyncSession, status: str) -> list[Contract]:
        return await self.contract_repo.get_by_status(db, status)

    async def get_by_rental_type(self, db: AsyncSession, rental_type: RentalType) -> list[Contract]:
        return await self.contract_repo.get_by_rental_type(db, rental_type)

    async def get_by_booking_source(self, db: AsyncSession, booking_source: str) -> list[Contract]:
        return await self.contract_repo.get_by_booking_source(db, booking_source)
