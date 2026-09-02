import uuid

from collections.abc import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repositories.base import BaseRepository
from app.receipts.models.receipt_template import ReceiptTemplate


class ReceiptTemplateRepository(BaseRepository[ReceiptTemplate, dict, dict]):
    """
    ReceiptTemplate-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update are inherited.
    """

    async def get_active_for_property(self, db: AsyncSession, property_id: uuid.UUID) -> ReceiptTemplate | None:
        return await self._first(db, self.model.property_id == property_id, self.model.is_active.is_(True))

    async def get_active_global(self, db: AsyncSession) -> ReceiptTemplate | None:
        return await self._first(db, self.model.property_id.is_(None), self.model.is_active.is_(True))

    async def get_by_property(self, db: AsyncSession, property_id: uuid.UUID) -> Sequence[ReceiptTemplate]:
        return await self._all(db, self.model.property_id == property_id)

    async def get_global_templates(self, db: AsyncSession) -> Sequence[ReceiptTemplate]:
        return await self._all(db, self.model.property_id.is_(None))


# Instantiate once — import this instance everywhere
receipt_template_repo = ReceiptTemplateRepository(ReceiptTemplate)
