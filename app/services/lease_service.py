from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.contract import Contract, RentalType
from app.models.lease import Lease
from app.models.user import User
from app.repositories.contract import ContractRepository
from app.repositories.lease import LeaseRepository
from app.schemas.base import PaginatedResponse
from app.schemas.lease import LeaseCreate, LeaseUpdate
from app.services.audit import write_audit_log
from app.services.base import ResourceAuthorizationMixin
from app.services.utils import integrity_error_message
from app.services.exceptions import (
    LeaseAlreadyExistsError,
    LeaseForbiddenError,
    LeaseRentalTypeError,
    RelatedResourceNotFoundError,
)


@dataclass(frozen=True)
class LeaseContext:
    lease: Lease | None
    contract: Contract
    contract_id: UUID


class LeaseService(ResourceAuthorizationMixin):
    """Business logic for `Lease` entities — long-term billing terms, 1:1 with `Contract`."""

    forbidden_error = LeaseForbiddenError

    def __init__(
        self,
        lease_repo: LeaseRepository,
        contract_repo: ContractRepository | None = None,
        property_repo=None,
    ) -> None:
        self.lease_repo = lease_repo
        self.contract_repo = contract_repo
        self.property_repo = property_repo

    async def list_leases(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[Lease]:
        """Admins see every lease; managers only see leases on contracts for properties they own."""
        return await self._list_scoped_by_manager(db, current_user, self.lease_repo, skip, limit)

    async def get_lease(self, db: AsyncSession, lease_id: UUID, current_user: User) -> Lease:
        lease = await self.lease_repo.get_by_id(db, lease_id)
        if not lease:
            raise RelatedResourceNotFoundError(f"Lease {lease_id} not found.")

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=lease.contract_id,
        )
        return lease

    async def get_by_contract(self, db: AsyncSession, contract_id: UUID, current_user: User) -> Lease | None:
        lease = await self.lease_repo.get_by_contract(db, contract_id)
        if not lease:
            return None

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=lease.contract_id,
        )
        return lease

    async def create_lease(
        self,
        db: AsyncSession,
        payload: LeaseCreate,
        current_user: User,
    ) -> Lease:
        """
        Relies on a DB constraint (not a pre-check) to prevent two concurrent
        requests both creating a Lease for the same contract; a resulting
        IntegrityError is translated into `LeaseAlreadyExistsError`.
        """
        ctx = await self._prepare_lease_context(db, current_user, contract_id=payload.contract_id)

        if ctx.contract.rental_type != RentalType.long_term:
            raise LeaseRentalTypeError(
                f"Contract {ctx.contract.id} is not long_term — a Lease can only be created for a long-term contract."
            )

        try:
            lease = await self.lease_repo.create(db, payload)
            write_audit_log(db, current_user, AuditAction.CREATE, "Lease", lease.id)
            await db.commit()
            return lease
        except IntegrityError as e:
            self._raise_if_duplicate_lease_conflict(e)
            raise

    async def update_lease(
        self,
        db: AsyncSession,
        lease_id: UUID,
        payload: LeaseUpdate,
        current_user: User,
    ) -> Lease | None:
        await self.get_lease(db, lease_id, current_user=current_user)

        lease = await self.lease_repo.update(db, lease_id, payload)
        write_audit_log(db, current_user, AuditAction.UPDATE, "Lease", lease_id)
        await db.commit()
        return lease

    async def delete_lease(
        self,
        db: AsyncSession,
        lease_id: UUID,
        current_user: User,
    ) -> Lease | None:
        await self.get_lease(db, lease_id, current_user=current_user)

        lease = await self.lease_repo.delete(db, lease_id)
        write_audit_log(db, current_user, AuditAction.DELETE, "Lease", lease_id)
        await db.commit()
        return lease

    async def _prepare_lease_context(
        self,
        db: AsyncSession,
        current_user: User,
        contract_id: UUID,
    ) -> LeaseContext:
        await self._validate_related_resources(db, contract_id=contract_id)
        contract = await self._get_contract(db, contract_id)

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=contract_id,
            contract=contract,
        )

        return LeaseContext(lease=None, contract=contract, contract_id=contract_id)

    @staticmethod
    def _raise_if_duplicate_lease_conflict(e: IntegrityError) -> None:
        """
        Translate a violation of `uq_lease_contract_id` into
        `LeaseAlreadyExistsError`; leaves unrelated IntegrityErrors for the
        caller to re-raise as is.
        """
        msg = integrity_error_message(e)
        if "uq_lease_contract_id" in msg or ("duplicate key value" in msg and "contract_id" in msg):
            raise LeaseAlreadyExistsError("A lease already exists for this contract.")
