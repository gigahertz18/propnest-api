"""
Shared audit-writing helper.

Not a `ResourceAuthorizationMixin` method: `UserService` doesn't inherit
that mixin (it has no property/contract/tenant resolution to share), so a
plain function importable by all six mutating services — the same shape
as `integrity_error_message` in `app/services/utils.py` — is the smallest
way to give every service the same call without forcing an unrelated
composition change onto `UserService`.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit_log import AuditAction, AuditLog
from app.models.user import User


def write_audit_log(
    db: AsyncSession,
    current_user: User,
    action: AuditAction,
    entity_type: str,
    entity_id: UUID,
    diff: dict[str, Any] | None = None,
) -> None:
    """
    Add an `AuditLog` row to the session — does not flush or commit.
    Callers add this immediately before their own `await db.commit()` so
    the audit row is part of the same transaction as the underlying
    change: a rolled-back mutation never leaves an orphaned audit row.
    """
    db.add(
        AuditLog(
            actor_id=getattr(current_user, "id", None),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            diff=diff,
        )
    )
