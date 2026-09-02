from __future__ import annotations

import logging

from collections.abc import Sequence
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit_log import AuditAction
from app.models.receipt import Receipt
from app.identity.models.user import User
from app.repositories.contract import ContractRepository
from app.repositories.payment import PaymentRepository
from app.properties.repositories.property import PropertyRepository
from app.repositories.receipt import ReceiptRepository
from app.crm.repositories.tenant import TenantRepository
from app.schemas.document import DocumentCreate
from app.core.services.audit import write_audit_log
from app.core.services.base import ResourceAuthorizationMixin
from app.services.document_service import DocumentService
from app.core.services.exceptions import (
    ReceiptCreationError,
    ReceiptForbiddenError,
    RelatedResourceNotFoundError,
)
from app.services.receipt_pdf import load_default_template, render_receipt_pdf
from app.services.receipt_template_service import ReceiptTemplateService

logger = logging.getLogger(__name__)


class ReceiptService(ResourceAuthorizationMixin):
    """Business logic for `Receipt` entities.

    Append-only: issuing a receipt for a payment always creates a brand-new
    Receipt row (and a brand-new backing PDF Document) — a reprint is just
    calling `issue_receipt` again for the same payment_id, never mutating
    or re-rendering an existing Receipt/Document.
    """

    forbidden_error = ReceiptForbiddenError

    def __init__(
        self,
        receipt_repo: ReceiptRepository,
        payment_repo: PaymentRepository,
        document_service: DocumentService,
        contract_repo: ContractRepository | None = None,
        property_repo: PropertyRepository | None = None,
        tenant_repo: TenantRepository | None = None,
        receipt_template_service: ReceiptTemplateService | None = None,
    ) -> None:
        self.receipt_repo = receipt_repo
        self.payment_repo = payment_repo
        self.document_service = document_service
        self.contract_repo = contract_repo
        self.property_repo = property_repo
        self.tenant_repo = tenant_repo
        self.receipt_template_service = receipt_template_service

    async def issue_receipt(
        self,
        db: AsyncSession,
        payment_id: UUID,
        current_user: User,
        storage_client=None,
    ) -> Receipt:
        payment = await self._get_payment_or_404(db, payment_id)

        contract = await self._get_contract(db, payment.contract_id)
        if contract is None:
            raise RelatedResourceNotFoundError(f"Contract {payment.contract_id} not found.")

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=payment.contract_id,
            contract=contract,
        )

        property_ = await self._get_property(db, contract.property_id)
        if property_ is None:
            raise RelatedResourceNotFoundError(f"Property {contract.property_id} not found.")

        tenant = await self._get_tenant(db, contract.tenant_id)
        if tenant is None:
            raise RelatedResourceNotFoundError(f"Tenant {contract.tenant_id} not found.")

        receipt_number = await self.receipt_repo.next_receipt_number(db)

        if self.receipt_template_service is not None:
            template_html = await self.receipt_template_service.resolve_active_template_html(
                db, property_.id, storage_client
            )
        else:
            template_html = load_default_template()

        pdf_buf = render_receipt_pdf(
            template_html=template_html,
            receipt_number=receipt_number,
            payment=payment,
            property_=property_,
            tenant=tenant,
        )

        # contract_id links the generated PDF to the same contract as the
        # payment: gives DocumentService's own authorization something to
        # resolve against (a manager who owns this contract's property must
        # also be allowed to create the Document backing the receipt), and
        # keeps the receipt PDF discoverable alongside other contract docs.
        doc_payload = DocumentCreate(
            file_name=f"receipt_{receipt_number}.pdf",
            file_type="application/pdf",
            contract_id=payment.contract_id,
        )
        document = await self.document_service.create_document(
            db,
            doc_payload,
            current_user,
            storage_client=storage_client,
            file_obj=pdf_buf,
        )

        try:
            receipt = await self.receipt_repo.create(
                db,
                {
                    "id": uuid4(),
                    "receipt_number": receipt_number,
                    "payment_id": payment.id,
                    "document_id": document.id,
                },
            )
            write_audit_log(db, current_user, AuditAction.CREATE, "Receipt", receipt.id)
            await db.commit()
            return receipt
        except Exception:
            logger.critical(
                f"Receipt row could not be created for payment {payment.id} after Document "
                f"{document.id} was already committed — orphaned Document needs manual reconciliation."
            )
            raise ReceiptCreationError(f"Failed to create receipt for payment {payment_id}.")

    async def list_receipts_for_payment(
        self,
        db: AsyncSession,
        payment_id: UUID,
        current_user: User,
    ) -> Sequence[Receipt]:
        payment = await self._get_payment_or_404(db, payment_id)
        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=payment.contract_id,
        )
        return await self.receipt_repo.get_by_payment(db, payment_id)

    async def get_receipt(
        self,
        db: AsyncSession,
        receipt_id: UUID,
        current_user: User,
    ) -> Receipt:
        receipt = await self.receipt_repo.get_by_id(db, receipt_id)
        if not receipt:
            raise RelatedResourceNotFoundError(f"Receipt {receipt_id} not found.")

        payment = await self._get_payment_or_404(db, receipt.payment_id)
        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=payment.contract_id,
        )
        return receipt

    async def get_receipt_document(
        self,
        db: AsyncSession,
        receipt_id: UUID,
        current_user: User,
        storage_client,
    ):
        receipt = await self.get_receipt(db, receipt_id, current_user)
        return await self.document_service.get_document_content(db, receipt.document_id, current_user, storage_client)

    async def _get_payment_or_404(self, db: AsyncSession, payment_id: UUID):
        payment = await self.payment_repo.get_by_id(db, payment_id)
        if not payment:
            raise RelatedResourceNotFoundError(f"Payment {payment_id} not found.")
        return payment
