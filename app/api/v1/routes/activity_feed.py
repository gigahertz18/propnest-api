from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_activity_feed_service, require_manager_or_above
from app.db.session import get_db
from app.identity.models.user import User
from app.core.schemas.audit_log import AuditLogResponse
from app.core.schemas.base import PaginatedResponse
from app.services.activity_feed_service import ActivityFeedService

router = APIRouter(tags=["Activity Feed"])


@router.get(
    "/properties/{property_id}/activity",
    response_model=PaginatedResponse[AuditLogResponse],
)
async def get_property_activity(
    property_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    activity_feed_service: ActivityFeedService = Depends(get_activity_feed_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Chronological feed of audit events for a property, its contracts,
    documents, and payments."""
    return await activity_feed_service.get_property_activity(
        db, property_id, current_user=current_user, skip=skip, limit=limit
    )
