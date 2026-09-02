import uuid

from collections.abc import Sequence
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repositories.base import BaseRepository
from app.core.models.audit_log import AuditLog
from app.leasing.models.contract import Contract
from app.models.document import Document
from app.models.payment import Payment


class ActivityFeedRepository(BaseRepository[AuditLog, dict, dict]):
    """
    Read-only queries deriving a per-property activity feed from `AuditLog`
    rows. `create`/`update`/`delete` are inherited but never called — audit
    rows are appended directly via `app.core.services.audit.write_audit_log` and
    are never modified or deleted (mirrors `AuditLogRepository`).
    """

    async def get_property_entries(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Sequence[AuditLog]:
        """Audit rows recorded directly against the property itself."""
        return await self._all(db, self.model.entity_type == "Property", self.model.entity_id == property_id)

    async def get_contract_entries(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Sequence[AuditLog]:
        """Audit rows for contracts belonging to the property."""
        contract_ids = select(Contract.id).where(Contract.property_id == property_id)
        return await self._all(db, self.model.entity_type == "Contract", self.model.entity_id.in_(contract_ids))

    async def get_document_entries(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Sequence[AuditLog]:
        """Audit rows for documents attached to the property, either
        directly (document.property_id) or via one of its contracts
        (document.contract_id -> contract.property_id) — mirrors
        `DocumentRepository.get_all_for_manager`'s OR-shape."""
        contract_ids = select(Contract.id).where(Contract.property_id == property_id)
        document_ids = select(Document.id).where(
            or_(
                Document.property_id == property_id,
                and_(Document.contract_id.is_not(None), Document.contract_id.in_(contract_ids)),
            )
        )
        return await self._all(db, self.model.entity_type == "Document", self.model.entity_id.in_(document_ids))

    async def get_payment_entries(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Sequence[AuditLog]:
        """Audit rows for payments whose contract belongs to the property.
        Every payment carries a non-nullable contract_id, so there's no
        "unattached resource" branch here (mirrors PaymentRepository's
        manager-scoping query)."""
        payment_ids = (
            select(Payment.id)
            .join(Contract, Contract.id == Payment.contract_id)
            .where(Contract.property_id == property_id)
        )
        return await self._all(db, self.model.entity_type == "Payment", self.model.entity_id.in_(payment_ids))


# Instantiate once — import this instance everywhere
activity_feed_repo = ActivityFeedRepository(AuditLog)
