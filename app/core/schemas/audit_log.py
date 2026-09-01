import uuid

from datetime import datetime

from app.core.models.audit_log import AuditAction
from app.core.schemas.base import BaseResponse


class AuditLogResponse(BaseResponse):
    """Returned to the client — audit rows are read-only, so there's no
    Create/Update schema: they're never constructed from a request body."""

    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: AuditAction
    entity_type: str
    entity_id: uuid.UUID
    diff: dict | None
    created_at: datetime
