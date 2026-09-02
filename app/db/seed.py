"""
Idempotent bootstrap helpers for system-managed (non-human) identities.
Kept out of app/identity/repositories/user.py since this makes policy decisions
(role, fields, password-hash generation) a thin CRUD repository
shouldn't own — and out of scripts/ since scripts/seed_system_user.py is
a thin CLI wrapper around this, not the other way around.
"""

import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.identity.models.user import User, UserRole


async def seed_system_user(db: AsyncSession) -> tuple[User, bool]:
    """
    Idempotent — returns the existing row if one already exists for
    settings.SYSTEM_SCHEDULER_USER_ID, creates it otherwise. Returns
    (user, created) so callers can distinguish the two cases for
    logging/display without duplicating the lookup-or-create logic.

    Shared by scripts/seed_system_user.py (manual/explicit invocation)
    and app/jobs/billing_jobs.py's on_startup — a fresh environment
    never needs a separate manual seeding step; the worker seeds itself
    the first time it boots.
    """
    system_user_id = uuid.UUID(settings.SYSTEM_SCHEDULER_USER_ID)

    existing = (await db.execute(select(User).where(User.id == system_user_id))).scalar_one_or_none()
    if existing:
        return existing, False

    unusable_password = secrets.token_urlsafe(64)
    system_user = User(
        id=system_user_id,
        username=settings.SYSTEM_SCHEDULER_USERNAME,
        email=settings.SYSTEM_SCHEDULER_EMAIL,
        full_name="PropNest Billing Scheduler",
        password_hash=hash_password(unusable_password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(system_user)
    await db.commit()
    await db.refresh(system_user)
    return system_user, True
