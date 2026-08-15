import uuid

from collections.abc import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.audit_log import AuditLog


class AuditLogRepository(BaseRepository[AuditLog, dict, dict]):
    """
    Read-only queries on top of the generic BaseRepository. `get_all` and
    `get_by_id` are inherited; `create`/`update`/`delete` exist on the base
    class but are never called here — audit rows are appended directly via
    `app.services.audit.write_audit_log` and are never modified or deleted.
    """

    async def get_filtered(
        self,
        db: AsyncSession,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[AuditLog]:
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        criteria = []
        if entity_type is not None:
            criteria.append(self.model.entity_type == entity_type)
        if entity_id is not None:
            criteria.append(self.model.entity_id == entity_id)

        return await self._all(db, *criteria, offset=skip, limit=limit)

    async def count_filtered(
        self,
        db: AsyncSession,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> int:
        criteria = []
        if entity_type is not None:
            criteria.append(self.model.entity_type == entity_type)
        if entity_id is not None:
            criteria.append(self.model.entity_id == entity_id)

        return await self._count(db, *criteria)


# Instantiate once — import this instance everywhere
audit_log_repo = AuditLogRepository(AuditLog)
