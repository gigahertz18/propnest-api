from collections.abc import Sequence
from datetime import date
from uuid import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.tenant import TenantRepository
from app.repositories.user import UserRepository
from app.schemas.tenant import TenantCreate, TenantUpdate
from app.models.tenant import Tenant
from app.services.exceptions import (
    RelatedResourceNotFoundError,
    UserNotFoundError,
    TenantAlreadyLinkedError,
)


class TenantService:
    """Business logic for `Tenant` entities."""

    def __init__(
        self,
        tenant_repo: TenantRepository,
        user_repo: UserRepository | None = None,
    ) -> None:
        self.tenant_repo = tenant_repo
        self.user_repo = user_repo

    async def list_tenants(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Tenant]:
        return await self.tenant_repo.get_all(db, skip=skip, limit=limit)

    async def get_tenant(self, db: AsyncSession, id: UUID) -> Tenant | None:
        return await self.tenant_repo.get_by_id(db, id)

    async def create_tenant(self, db: AsyncSession, payload: TenantCreate) -> Tenant:
        tenant = await self.tenant_repo.create(db, payload)
        await db.commit()
        return tenant

    async def update_tenant(self, db: AsyncSession, id: UUID, payload: TenantUpdate) -> Tenant | None:
        tenant = await self.tenant_repo.update(db, id, payload)
        await db.commit()
        return tenant

    async def delete_tenant(self, db: AsyncSession, tenant_id: UUID) -> Tenant | None:
        tenant = await self.tenant_repo.delete(db, tenant_id)
        await db.commit()
        return tenant

    async def get_by_email(self, db: AsyncSession, email: str) -> Tenant | None:
        return await self.tenant_repo.get_by_email(db, email)

    async def get_by_phone_number(self, db: AsyncSession, phone_number: str) -> Tenant | None:
        return await self.tenant_repo.get_by_phone_number(db, phone_number)

    async def get_by_full_name(self, db: AsyncSession, full_name: str) -> Sequence[Tenant]:
        return await self.tenant_repo.get_by_full_name(db, full_name)

    async def get_by_occupation(self, db: AsyncSession, occupation: str) -> Sequence[Tenant]:
        return await self.tenant_repo.get_by_occupation(db, occupation)

    async def get_by_date_of_birth(self, db: AsyncSession, date_of_birth: date) -> Sequence[Tenant]:
        return await self.tenant_repo.get_by_date_of_birth(db, date_of_birth)

    async def get_by_user_id(self, db: AsyncSession, user_id: UUID) -> Tenant | None:
        return await self.tenant_repo.get_by_user_id(db, user_id)

    async def link_user(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> Tenant:
        """
        Link a tenant to a portal-access `User` account.

        Nullable + unique on `tenant.user_id` means a tenant can exist
        before they have portal access, and get linked/invited later.
        Both sides of the 1:1 are checked explicitly so callers get a
        specific domain exception rather than a raw `IntegrityError` —
        the unique constraint on `tenant.user_id` remains as the final
        backstop against races between concurrent requests.
        """
        tenant = await self.tenant_repo.get_by_id(db, tenant_id)
        if not tenant:
            raise RelatedResourceNotFoundError(f"Tenant {tenant_id} not found.")

        user = await self.user_repo.get_by_id(db, user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found.")

        if tenant.user_id is not None and tenant.user_id != user_id:
            raise TenantAlreadyLinkedError(f"Tenant {tenant_id} is already linked to a different user.")

        existing_link = await self.tenant_repo.get_by_user_id(db, user_id)
        if existing_link and existing_link.id != tenant_id:
            raise TenantAlreadyLinkedError(f"User {user_id} is already linked to a different tenant.")

        try:
            tenant = await self.tenant_repo.update(db, tenant_id, {"user_id": user_id})
            await db.commit()
            return tenant
        except IntegrityError as e:
            await db.rollback()
            msg = str(e.orig) if getattr(e, "orig", None) is not None else str(e)
            if "ix_tenants_user_id" in msg or "tenants_user_id" in msg:
                raise TenantAlreadyLinkedError(f"User {user_id} is already linked to a different tenant.")
            raise

    async def unlink_user(self, db: AsyncSession, tenant_id: UUID) -> Tenant:
        """Remove portal-access linkage, leaving the tenant record intact."""
        tenant = await self.tenant_repo.get_by_id(db, tenant_id)
        if not tenant:
            raise RelatedResourceNotFoundError(f"Tenant {tenant_id} not found.")

        tenant = await self.tenant_repo.update(db, tenant_id, {"user_id": None})
        await db.commit()
        return tenant
