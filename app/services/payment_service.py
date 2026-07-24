from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment
from app.models.user import User
from app.repositories.contract import ContractRepository
from app.repositories.payment import PaymentRepository
from app.repositories.property import PropertyRepository
from app.schemas.base import PaginatedResponse
from app.schemas.payment import PaymentCreate, PaymentUpdate
from app.services.base import ResourceAuthorizationMixin
from app.services.exceptions import PaymentForbiddenError, RelatedResourceNotFoundError


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
        current_user: User | None = None,
    ) -> Payment:
        ctx = await self._prepare_payment_context(
            db,
            payment=None,
            contract_id=payload.contract_id,
            current_user=current_user,
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
        current_user: User | None = None,
    ) -> Payment | None:
        payment = await self._get_payment_or_404(db, payment_id)

        # this is for authorization only. no need to use the returned context
        await self._prepare_payment_context(
            db,
            payment=payment,
            contract_id=payment.contract_id,
            current_user=current_user,
        )

        payment = await self.payment_repo.update(db, payment_id, payload)
        await db.commit()
        return payment

    async def delete_payment(
        self,
        db: AsyncSession,
        payment_id: UUID,
        current_user: User | None = None,
    ) -> Payment | None:
        payment = await self._get_payment_or_404(db, payment_id)

        await self._prepare_payment_context(
            db,
            payment=payment,
            contract_id=payment.contract_id,
            current_user=current_user,
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
        payment: Payment | None = None,
        contract_id: UUID | None = None,
        current_user: User | None = None,
    ) -> PaymentContext:
        effective_contract_id = contract_id if contract_id is not None else payment.contract_id if payment else None

        await self._validate_related_resources(db, contract_id=effective_contract_id)

        if current_user:
            await self._authorize_user_to_property(
                db,
                current_user,
                property_id=None,
                contract_id=effective_contract_id,
            )

        return PaymentContext(
            payment=payment,
            contract_id=effective_contract_id,
        )
