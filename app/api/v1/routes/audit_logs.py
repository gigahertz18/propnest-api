from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_audit_log_service, require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.audit_log import AuditLogResponse
from app.schemas.base import PaginatedResponse
from app.services.audit_log_service import AuditLogService

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("/", response_model=PaginatedResponse[AuditLogResponse])
async def list_audit_logs(
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    audit_log_service: AuditLogService = Depends(get_audit_log_service),
    current_user: User = Depends(require_admin),
):
    """List audit log entries, optionally filtered by entity_type/entity_id. Admin only."""
    return await audit_log_service.list_audit_logs(
        db, entity_type=entity_type, entity_id=entity_id, skip=skip, limit=limit
    )
