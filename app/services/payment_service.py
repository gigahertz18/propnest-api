from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit_log import AuditAction
from app.models.contract import Contract
from app.models.payment import Payment, PaymentStatus
from app.models.user import User
from app.repositories.billing_record import BillingRecordRepository
from app.repositories.contract import ContractRepository
from app.repositories.lease import LeaseRepository
from app.repositories.payment import PaymentRepository
from app.repositories.property import PropertyRepository
from app.core.schemas.base import PaginatedResponse
from app.schemas.payment import PaymentCorrectionCreate, PaymentCreate, PaymentUpdate
from app.core.services.audit import write_audit_log
from app.core.services.base import ResourceAuthorizationMixin
from app.core.services.exceptions import (
    PaymentAlreadyVoidedError,
    PaymentForbiddenError,
    RelatedResourceNotFoundError,
)
from app.services.lease_billing_service import LeaseBillingService


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
        billing_record_repo: BillingRecordRepository | None = None,
        lease_repo: LeaseRepository | None = None,
        lease_billing_service: LeaseBillingService | None = None,
    ) -> None:
        self.payment_repo = payment_repo
        self.contract_repo = contract_repo
        self.property_repo = property_repo
        self.billing_record_repo = billing_record_repo
        self.lease_repo = lease_repo
        self.lease_billing_service = lease_billing_service

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

        billing_record = None
        if payload.billing_record_id is not None:
            billing_record = await self._get_billing_record_for_contract(db, payload.billing_record_id, ctx.contract_id)

        resolved_payload = payload.model_copy(update={"contract_id": ctx.contract_id})

        payment = await self.payment_repo.create(db, resolved_payload)
        write_audit_log(db, current_user, AuditAction.CREATE, "Payment", payment.id)

        if billing_record is not None:
            await self._apply_payment_to_billing_record(db, billing_record)

        await db.commit()
        return payment

    async def _get_billing_record_for_contract(self, db: AsyncSession, billing_record_id: UUID, contract_id: UUID):
        billing_record = await self.billing_record_repo.get_by_id(db, billing_record_id)
        if billing_record is None:
            raise RelatedResourceNotFoundError(f"BillingRecord {billing_record_id} not found.")

        lease = await self.lease_repo.get_by_id(db, billing_record.lease_id)
        if lease is None:
            raise RelatedResourceNotFoundError(f"Lease {billing_record.lease_id} not found.")

        if lease.contract_id != contract_id:
            raise RelatedResourceNotFoundError(
                f"BillingRecord {billing_record_id} does not belong to contract {contract_id}."
            )

        return billing_record

    async def _apply_payment_to_billing_record(self, db: AsyncSession, billing_record) -> None:
        payments = await self.payment_repo.get_by_billing_record(db, billing_record.id)
        cumulative_paid = sum(
            (p.amount for p in payments if p.status != PaymentStatus.VOIDED),
            start=Decimal("0"),
        )
        self.lease_billing_service.apply_payment(billing_record, cumulative_paid)
        await db.flush()

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
        write_audit_log(db, current_user, AuditAction.UPDATE, "Payment", payment_id)
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
        write_audit_log(db, current_user, AuditAction.CREATE, "Payment", new_payment.id)
        write_audit_log(db, current_user, AuditAction.UPDATE, "Payment", original.id)
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
        write_audit_log(db, current_user, AuditAction.DELETE, "Payment", payment_id)
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
