from __future__ import annotations

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit_log import AuditLog
from app.core.repositories.audit_log import AuditLogRepository
from app.core.schemas.base import PaginatedResponse


class AuditLogService:
    """
    Read-only query layer for `AuditLog` entries.

    Audit rows are never created here — see `app.core.services.audit.write_audit_log`,
    called directly by each of the six mutating services alongside their own
    `db.commit()`. This service only exists to serve the admin-only query route.
    """

    def __init__(self, audit_log_repo: AuditLogRepository) -> None:
        self.audit_log_repo = audit_log_repo

    async def list_audit_logs(
        self,
        db: AsyncSession,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[AuditLog]:
        items = await self.audit_log_repo.get_filtered(
            db, entity_type=entity_type, entity_id=entity_id, skip=skip, limit=limit
        )
        total = await self.audit_log_repo.count_filtered(db, entity_type=entity_type, entity_id=entity_id)
        return PaginatedResponse(items=items, total=total)
