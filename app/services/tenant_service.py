from datetime import date
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.tenant import TenantRepository
from app.schemas.tenant import TenantCreate, TenantUpdate
from app.models.tenant import Tenant


class TenantService:
    """Business logic for `Tenant` entities."""

    def __init__(self, tenant_repo: TenantRepository) -> None:
        self.tenant_repo = tenant_repo

    async def list_tenants(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Tenant]:
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

    async def delete_tenant(self, db: AsyncSession, id: UUID) -> Tenant | None:
        tenant = await self.tenant_repo.delete(db, id)
        await db.commit()
        return tenant

    async def get_by_email(self, db: AsyncSession, email: str) -> Tenant | None:
        return await self.tenant_repo.get_by_email(db, email)

    async def get_by_phone_number(self, db: AsyncSession, phone_number: str) -> Tenant | None:
        return await self.tenant_repo.get_by_phone_number(db, phone_number)

    async def get_by_full_name(self, db: AsyncSession, full_name: str) -> list[Tenant]:
        return await self.tenant_repo.get_by_full_name(db, full_name)

    async def get_by_occupation(self, db: AsyncSession, occupation: str) -> list[Tenant]:
        return await self.tenant_repo.get_by_occupation(db, occupation)

    async def get_by_date_of_birth(self, db: AsyncSession, date_of_birth: date) -> list[Tenant]:
        return await self.tenant_repo.get_by_date_of_birth(db, date_of_birth)
