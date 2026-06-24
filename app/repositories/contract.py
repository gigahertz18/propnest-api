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

    # def get_by_property(
    #     self,
    #     db: AsyncSession,
    #     property_id: uuid.UUID,
    # ) -> list[Contract]:
    #     """Return all contracts linked to a given property."""
    #     return db.query(self.model).filter(self.model.property_id == property_id).all()
    
    async def get_by_property(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> list[Contract]:
        """Return all contracts linked to a given property."""
        statement = select(self.model).where(self.model.property_id == property_id)
        result = await db.execute(statement)
        
        return result.scalars().all()

    # def get_by_tenant(
    #     self,
    #     db: AsyncSession,
    #     tenant_id: uuid.UUID,
    # ) -> list[Contract]:
    #     """Return all contracts linked to a given tenant."""
    #     return db.query(self.model).filter(self.model.tenant_id == tenant_id).all()
    
    async def get_by_tenant(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> list[Contract]:
        """Return all contracts linked to a given tenant."""
        statement = select(self.model).where(self.model.tenant_id == tenant_id)
        result = await db.execute(statement)
        return result.scalars().all()

    # def get_by_status(
    #     self,
    #     db: AsyncSession,
    #     status: str,
    # ) -> list[Contract]:
    #     """Return all contracts with a given status (e.g. ACTIVE, EXPIRED)."""
    #     return db.query(self.model).filter(self.model.status == status).all()
    async def get_by_status(
        self,
        db: AsyncSession,
        status: str,
    ) -> list[Contract]:
        """Return all contracts with a given status (e.g. ACTIVE, EXPIRED)."""
        statement = select(self.model).where(self.model.status == status)
        result = await db.execute(statement)
        
        return result.scalars().all()

    # def get_by_rental_type(
    #     self,
    #     db: AsyncSession,
    #     rental_type: RentalType,
    # ) -> list[Contract]:
    #     """Return all contracts of a given rental type."""
    #     return db.query(self.model).filter(self.model.rental_type == rental_type).all()
    async def get_by_rental_type(
        self,
        db: AsyncSession,
        rental_type: RentalType,
    ) -> list[Contract]:
        """Return all contracts of a given rental type."""
        statement = select(self.model).where(self.model.rental_type == rental_type)
        result = await db.execute(statement)
        
        return result.scalars().all()

    # def get_by_booking_source(
    #     self,
    #     db: AsyncSession,
    #     booking_source: str,
    # ) -> list[Contract]:
    #     """Return all contracts originating from a given booking source."""
    #     return db.query(self.model).filter(self.model.booking_source == booking_source).all()
    
    async def get_by_booking_source(
        self,
        db: AsyncSession,
        booking_source: str,
    ) -> list[Contract]:
        """Return all contracts originating from a given booking source."""
        statement = select(self.model).where(self.model.booking_source == booking_source)
        result = await db.execute(statement)
        
        return result.scalars().all()

    # def get_active_contract_by_property(
    #     self,
    #     db: AsyncSession,
    #     property_id: uuid.UUID,
    # ) -> Contract | None:
    #     """
    #     Return the single active contract for a property, if one exists.
    #     Useful for checking occupancy before creating a new contract.
    #     """
    #     return (
    #         db.query(self.model)
    #         .filter(
    #             self.model.property_id == property_id,
    #             self.model.status == "ACTIVE",
    #         )
    #         .first()
    #     )
    
    async def get_active_contract_by_property(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Contract | None:
        """
        Return the single active contract for a property, if one exists.
        Useful for checking occupancy before creating a new contract.
        """
        
        statement = select(self.model).where(
            self.model.property_id == property_id,
            self.model.status == "ACTIVE",
        )
        
        result = await db.execute(statement)
        
        return result.scalars().first()
        

# Instantiate once — import this instance everywhere
contract_repo = ContractRepository(Contract)
