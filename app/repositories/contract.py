import uuid
from sqlalchemy import select

# from sqlalchemy.orm import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.contract import Contract, RentalType
from app.schemas.contract import ContractCreate, ContractUpdate


class ContractRepository(BaseRepository[Contract, ContractCreate, ContractUpdate]):
    """
    Contract-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    async def get_by_property(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> list[Contract]:
        """Return all contracts linked to a given property."""
        
        return await self._all(
            db,
            self.model.property_id == property_id
        )

    async def get_by_tenant(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> list[Contract]:
        """Return all contracts linked to a given tenant."""
        return await self._all(
            db,
            self.model.tenant_id == tenant_id
        )

    async def get_by_status(
        self,
        db: AsyncSession,
        status: str,
    ) -> list[Contract]:
        """Return all contracts with a given status (e.g. ACTIVE, EXPIRED)."""

        return await self._all(
            db,
            self.model.status == status
        )

    async def get_by_rental_type(
        self,
        db: AsyncSession,
        rental_type: RentalType,
    ) -> list[Contract]:
        """Return all contracts of a given rental type."""

        return await self._all(
            db,
            self.model.rental_type == rental_type
        )

    async def get_by_booking_source(
        self,
        db: AsyncSession,
        booking_source: str,
    ) -> list[Contract]:
        """Return all contracts originating from a given booking source."""
        
        return await self._all(
            db,
            self.model.booking_source == booking_source
        )

    async def get_active_contract_by_property(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Contract | None:
        """
        Return the single active contract for a property, if one exists.
        Useful for checking occupancy before creating a new contract.
        """

        return await self._first(
            db,
            self.model.property_id == property_id,
            self.model.status == "ACTIVE"
        )


# Instantiate once — import this instance everywhere
contract_repo = ContractRepository(Contract)
