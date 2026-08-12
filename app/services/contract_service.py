from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract, RentalType
from app.models.user import User
from app.repositories.contract import ContractRepository
from app.repositories.property import PropertyRepository
from app.repositories.tenant import TenantRepository
from app.schemas.base import PaginatedResponse
from app.schemas.contract import ContractCreate, ContractUpdate
from app.services.base import ResourceAuthorizationMixin
from app.services.utils import integrity_error_message
from app.services.exceptions import (
    ContractActiveError,
    ContractForbiddenError,
    ContractInUseError,
    RelatedResourceNotFoundError,
)


@dataclass(frozen=True)
class ContractContext:

    contract: Contract | None
    property_id: UUID | None
    tenant_id: UUID | None


class ContractService(ResourceAuthorizationMixin):
    """Business logic for rental `Contract` entities."""

    forbidden_error = ContractForbiddenError

    def __init__(
        self,
        contract_repo: ContractRepository,
        property_repo: PropertyRepository | None = None,
        tenant_repo: TenantRepository | None = None,
    ) -> None:
        self.contract_repo = contract_repo
        self.property_repo = property_repo
        self.tenant_repo = tenant_repo

    async def list_contracts(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[Contract]:
        """Admins see every contract; managers only see contracts on properties they own."""

        return await self._list_scoped_by_manager(db, current_user, self.contract_repo, skip, limit)

    async def get_contract(self, db: AsyncSession, contract_id: UUID, current_user: User) -> Contract:
        contract = await self.contract_repo.get_by_id(db, contract_id)
        if not contract:
            raise RelatedResourceNotFoundError(f"Contract {contract_id} not found.")

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=contract.property_id,
            contract_id=None,
        )
        return contract

    async def create_contract(
        self,
        db: AsyncSession,
        payload: ContractCreate,
        current_user: User,
    ) -> Contract:
        """
        Relies on a DB constraint (not a pre-check) to prevent
        two concurrent requests both creating an ACTIVE contract for the same property;
        a resulting IntegrityError is translated into `ContractActiveError`
        """
        ctx = await self._prepare_contract_context(
            db,
            contract=None,
            property_id=payload.property_id,
            tenant_id=payload.tenant_id,
            current_user=current_user,
        )

        resolved_payload = payload.model_copy(
            update={
                "property_id": ctx.property_id,
                "tenant_id": ctx.tenant_id,
            }
        )

        try:
            contract = await self.contract_repo.create(db, resolved_payload)
            await db.commit()
            return contract
        except IntegrityError as e:
            self._raise_if_active_contract_conflict(e)
            raise

    async def update_contract(
        self,
        db: AsyncSession,
        contract_id: UUID,
        payload: ContractUpdate,
        current_user: User,
    ) -> Contract | None:
        """
        `ContractUpdate` can't change `property_id`, but it can flip `status`
        back to ACTIVE - same partial unique index as `create_contract`, translated the same way
        """
        contract = await self.get_contract(db, contract_id, current_user=current_user)

        try:

            contract = await self.contract_repo.update(db, contract_id, payload)
            await db.commit()
            return contract
        except IntegrityError as e:
            self._raise_if_active_contract_conflict(e)
            raise

    async def delete_contract(
        self,
        db: AsyncSession,
        contract_id: UUID,
        current_user: User,
    ) -> Contract | None:

        contract = await self.get_contract(db, contract_id, current_user=current_user)

        try:
            contract = await self.contract_repo.delete(db, contract_id)
            await db.commit()
            return contract
        except IntegrityError as e:
            raise ContractInUseError(
                f"Contract {contract_id} cannot be deleted because it is still referenced by "
                "an existing payment or document."
            ) from e

    async def get_by_property(self, db: AsyncSession, property_id: UUID) -> Sequence[Contract]:
        return await self.contract_repo.get_by_property(db, property_id)

    async def get_active_contract_by_property(self, db: AsyncSession, property_id: UUID) -> Contract | None:
        return await self.contract_repo.get_active_contract_by_property(db, property_id)

    async def get_by_tenant(self, db: AsyncSession, tenant_id: UUID) -> Sequence[Contract]:
        return await self.contract_repo.get_by_tenant(db, tenant_id)

    async def get_by_status(self, db: AsyncSession, status: str) -> Sequence[Contract]:
        return await self.contract_repo.get_by_status(db, status)

    async def get_by_rental_type(self, db: AsyncSession, rental_type: RentalType) -> Sequence[Contract]:
        return await self.contract_repo.get_by_rental_type(db, rental_type)

    async def get_by_booking_source(self, db: AsyncSession, booking_source: str) -> Sequence[Contract]:
        return await self.contract_repo.get_by_booking_source(db, booking_source)

    async def _prepare_contract_context(
        self,
        db: AsyncSession,
        current_user: User,
        contract: Contract | None = None,
        property_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> ContractContext:

        ids = self._resolve_ids(contract, property_id=property_id, tenant_id=tenant_id)
        await self._validate_related_resources(db, **ids)

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=ids["property_id"],
            contract_id=contract.id if contract else None,
        )

        return ContractContext(
            contract=contract,
            property_id=ids["property_id"],
            tenant_id=ids["tenant_id"],
        )

    @staticmethod
    def _raise_if_active_contract_conflict(e: IntegrityError) -> None:
        """
        Translate a violation of `uq_active_contract_property` into `ContractActiveError`;
        leaves unrelated IntegrityErrors for the caller to re-raise as is.
        """
        msg = integrity_error_message(e)
        if "uq_active_contract_property" in msg or ("duplicate key value" in msg and "property_id" in msg):
            raise ContractActiveError("An active contract already exists for this property")
