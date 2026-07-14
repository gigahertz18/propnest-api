import uuid

from collections.abc import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.document import Document
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


# Instantiate once — import this instance everywhere
document_repo = DocumentRepository(Document)
