import uuid

from collections.abc import Sequence
from sqlalchemy import select, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.document import Document
from app.models.contract import Contract
from app.models.property import Property
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate


class DocumentRepository(BaseRepository[Document, DocumentCreate, DocumentRelinkUpdate | DocumentFileUpdate]):
    """
    Document-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    async def get_by_contract(
        self,
        db: AsyncSession,
        contract_id: uuid.UUID,
    ) -> Sequence[Document]:
        """Return all documents linked to a given contract."""
        return await self._all(db, self.model.contract_id == contract_id)

    async def get_by_property(
        self,
        db: AsyncSession,
        property_id: uuid.UUID,
    ) -> Sequence[Document]:
        """Return all documents linked to a given property."""
        return await self._all(db, self.model.property_id == property_id)

    async def get_by_tenant(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> Sequence[Document]:
        """Return all documents linked to a given tenant."""
        return await self._all(db, self.model.tenant_id == tenant_id)

    async def get_by_type(
        self,
        db: AsyncSession,
        file_type: str,
    ) -> Sequence[Document]:
        """Return all documents of a given type (e.g. LEASE_AGREEMENT, ID_PROOF)."""
        return await self._all(db, self.model.file_type == file_type)

    async def get_all_for_manager(
        self,
        db: AsyncSession,
        manager_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Document]:
        """Documents a manager may see — those tied to one of their own
        properties, either directly (document.property_id) or indirectly
        through a contract (document.contract_id -> contract.property_id).

        A document that only carries a tenant_id (no property_id or
        contract_id) doesn't resolve to any property under this model —
        matching `_authorize_user_to_property`'s existing rule that an
        unresolved resource is manager-forbidden, admin-only. That's not a
        new restriction introduced here; it mirrors what already applies
        on the write side via `ResourceAuthorizationMixin`.
        """
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(Document)
            .outerjoin(Contract, Contract.id == Document.contract_id)
            .where(
                or_(
                    and_(Document.property_id.is_not(None), Document.property_id.in_(owned_property_ids)),
                    and_(Document.contract_id.is_not(None), Contract.property_id.in_(owned_property_ids)),
                )
            )
            .order_by(Document.created_at)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_all(self, db: AsyncSession) -> int:
        return await self._count(db)

    async def count_all_for_manager(self, db: AsyncSession, manager_id: uuid.UUID) -> int:
        owned_property_ids = select(Property.id).where(Property.manager_id == manager_id)

        stmt = (
            select(func.count())
            .select_from(Document)
            .outerjoin(Contract, Contract.id == Document.contract_id)
            .where(
                or_(
                    and_(Document.property_id.is_not(None), Document.property_id.in_(owned_property_ids)),
                    and_(Document.contract_id.is_not(None), Contract.property_id.in_(owned_property_ids)),
                )
            )
        )

        result = await db.execute(stmt)
        return int(result.scalar_one())


# Instantiate once — import this instance everywhere
document_repo = DocumentRepository(Document)
