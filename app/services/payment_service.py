from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract
from app.models.payment import Payment, PaymentStatus
from app.models.user import User
from app.repositories.contract import ContractRepository
from app.repositories.payment import PaymentRepository
from app.repositories.property import PropertyRepository
from app.schemas.base import PaginatedResponse
from app.schemas.payment import PaymentCorrectionCreate, PaymentCreate, PaymentUpdate
from app.services.base import ResourceAuthorizationMixin
from app.services.exceptions import (
    PaymentAlreadyVoidedError,
    PaymentForbiddenError,
    RelatedResourceNotFoundError,
)


@dataclass(frozen=True)
class PaymentContext:

    payment: Payment | None
    contract_id: UUID | None


class PaymentService(ResourceAuthorizationMixin):
    """Business logic for `Payment` entities.

    A payment always belongs to exactly one contract (`contract_id` is
    non-nullable on the model), so authorization always resolves through
    the contract-only path of `ResourceAuthorizationMixin` — there's no
    direct `property_id` on a payment the way there is on a `Contract`.
    """

    forbidden_error = PaymentForbiddenError

    def __init__(
        self,
        payment_repo: PaymentRepository,
        contract_repo: ContractRepository | None = None,
        property_repo: PropertyRepository | None = None,
    ) -> None:
        self.payment_repo = payment_repo
        self.contract_repo = contract_repo
        self.property_repo = property_repo

    async def list_payments(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[Payment]:
        """Admins see every payment; managers only see payments whose
        contract belongs to one of their own properties."""
        return await self._list_scoped_by_manager(db, current_user, self.payment_repo, skip, limit)

    async def get_payment(
        self,
        db: AsyncSession,
        payment_id: UUID,
        current_user: User,
    ) -> Payment:
        payment = await self._get_payment_or_404(db, payment_id)
        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=payment.contract_id,
        )
        return payment

    async def create_payment(
        self,
        db: AsyncSession,
        payload: PaymentCreate,
        current_user: User,
    ) -> Payment:
        ctx = await self._prepare_payment_context(
            db,
            current_user,
            payment=None,
            contract_id=payload.contract_id,
        )

        resolved_payload = payload.model_copy(update={"contract_id": ctx.contract_id})

        payment = await self.payment_repo.create(db, resolved_payload)
        await db.commit()
        return payment

    async def update_payment(
        self,
        db: AsyncSession,
        payment_id: UUID,
        payload: PaymentUpdate,
        current_user: User,
    ) -> Payment | None:
        payment = await self._get_payment_or_404(db, payment_id)

        # this is for authorization only. no need to use the returned context
        await self._prepare_payment_context(
            db,
            current_user,
            payment=payment,
            contract_id=payment.contract_id,
        )

        if payment.status == PaymentStatus.VOIDED:
            raise PaymentAlreadyVoidedError(f"Payment {payment_id} is voided and can no longer be modified.")

        payment = await self.payment_repo.update(db, payment_id, payload)
        await db.commit()
        return payment

    async def void_and_correct_payment(
        self,
        db: AsyncSession,
        payment_id: UUID,
        payload: PaymentCorrectionCreate,
        current_user: User,
    ) -> Payment:
        """Correct a mis-entered payment without mutating its history.

        Append-only: the original is marked VOIDED and a new payment row
        is created referencing it via `corrects_payment_id`, so a receipt
        already issued against the original never silently changes what
        it was for.
        """
        original = await self._get_payment_or_404(db, payment_id)

        # this is for authorization only. no need to use the returned context
        await self._prepare_payment_context(
            db,
            current_user,
            payment=original,
            contract_id=original.contract_id,
        )

        if original.status == PaymentStatus.VOIDED:
            raise PaymentAlreadyVoidedError(f"Payment {payment_id} is already voided and cannot be corrected again.")

        correction_data = payload.model_dump()
        correction_data["contract_id"] = original.contract_id
        correction_data["corrects_payment_id"] = original.id

        new_payment = await self.payment_repo.create(db, correction_data)
        await self.payment_repo.update(db, original.id, {"status": PaymentStatus.VOIDED})
        await db.commit()
        return new_payment

    async def delete_payment(
        self,
        db: AsyncSession,
        payment_id: UUID,
        current_user: User,
    ) -> Payment | None:
        payment = await self._get_payment_or_404(db, payment_id)

        await self._prepare_payment_context(
            db,
            current_user,
            payment=payment,
            contract_id=payment.contract_id,
        )

        payment = await self.payment_repo.delete(db, payment_id)
        await db.commit()
        return payment

    async def get_by_contract(self, db: AsyncSession, contract_id: UUID) -> Sequence[Payment]:
        return await self.payment_repo.get_by_contract(db, contract_id)

    async def get_by_status(self, db: AsyncSession, status: str) -> Sequence[Payment]:
        return await self.payment_repo.get_by_status(db, status)

    async def _get_payment_or_404(self, db: AsyncSession, payment_id: UUID) -> Payment:
        payment = await self.payment_repo.get_by_id(db, payment_id)
        if not payment:
            raise RelatedResourceNotFoundError(f"Payment {payment_id} not found.")
        return payment

    async def _prepare_payment_context(
        self,
        db: AsyncSession,
        current_user: User,
        payment: Payment | None = None,
        contract_id: UUID | None = None,
    ) -> PaymentContext:
        ids = self._resolve_ids(payment, contract_id=contract_id)

        contract: Contract | None = None
        if ids["contract_id"] is not None:
            contract = await self._get_contract(db, ids["contract_id"])
            if contract is None:
                raise RelatedResourceNotFoundError(f"Contract {ids['contract_id']} not found.")

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=ids["contract_id"],
            contract=contract,
        )

        return PaymentContext(
            payment=payment,
            **ids,
        )
