from __future__ import annotations

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit_log import AuditLog
from app.identity.models.user import UserRole
from app.reporting.repositories.activity_feed import ActivityFeedRepository
from app.properties.repositories.property import PropertyRepository
from app.core.schemas.base import PaginatedResponse
from app.core.services.exceptions import ActivityFeedForbiddenError, RelatedResourceNotFoundError


class ActivityFeedService:
    """
    Read-only, per-property activity feed derived from `AuditLog` rows —
    aggregates entries for the property itself plus its contracts,
    documents, and payments.
    """

    def __init__(self, activity_feed_repo: ActivityFeedRepository, property_repo: PropertyRepository) -> None:
        self.activity_feed_repo = activity_feed_repo
        self.property_repo = property_repo

    async def get_property_activity(
        self,
        db: AsyncSession,
        property_id: UUID,
        current_user,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[AuditLog]:
        """
        Fails closed like `PropertyService.get_property`: existence is
        checked before role, so ADMIN's ownership bypass never skips the
        404 case. Only ADMIN (bypass) and MANAGER (must own the property)
        are authorized.
        """
        prop = await self.property_repo.get_by_id(db, property_id)
        if not prop:
            raise RelatedResourceNotFoundError(f"Property {property_id} not found.")

        role = getattr(current_user, "role", None)
        is_admin = role == UserRole.ADMIN
        is_owning_manager = role == UserRole.MANAGER and current_user.id == prop.manager_id

        if not (is_admin or is_owning_manager):
            raise ActivityFeedForbiddenError(f"Property {prop.id}'s activity feed is not accessible for this user")

        entries = [
            *await self.activity_feed_repo.get_property_entries(db, property_id),
            *await self.activity_feed_repo.get_contract_entries(db, property_id),
            *await self.activity_feed_repo.get_document_entries(db, property_id),
            *await self.activity_feed_repo.get_payment_entries(db, property_id),
        ]
        entries.sort(key=lambda entry: (entry.created_at, entry.id), reverse=True)

        skip = max(0, skip)
        limit = min(max(0, limit), 100)
        return PaginatedResponse(items=entries[skip : skip + limit], total=len(entries))
