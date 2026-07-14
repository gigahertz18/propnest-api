import uuid

from collections.abc import Sequence
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate, TenantUpdate


class TenantRepository(BaseRepository[Tenant, TenantCreate, TenantUpdate]):
    """
    Tenant-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    async def get_by_email(
        self,
        db: AsyncSession,
        email: str,
    ) -> Tenant | None:

        return await self._first(
            db,
            self.model.email == email,
        )

    async def get_by_phone_number(
        self,
        db: AsyncSession,
        phone_number: str,
    ) -> Tenant | None:

        return await self._first(db, self.model.phone_number == phone_number)

    async def get_by_full_name(
        self,
        db: AsyncSession,
        full_name: str,
    ) -> Sequence[Tenant]:
        # return db.query(self.model).filter(self.model.full_name.ilike(f"%{full_name}%")).all()
        return await self._all(db, self.model.full_name.ilike(f"%{full_name}%"))

    async def get_by_occupation(
        self,
        db: AsyncSession,
        occupation: str,
    ) -> Sequence[Tenant]:
        # return db.query(self.model).filter(self.model.occupation.ilike(f"%{occupation}%")).all()
        return await self._all(db, self.model.occupation.ilike(f"%{occupation}%"))

    async def get_by_date_of_birth(
        self,
        db: AsyncSession,
        date_of_birth: date,
    ) -> Sequence[Tenant]:
        # return db.query(self.model).filter(self.model.date_of_birth == date_of_birth).all()
        return await self._all(db, self.model.date_of_birth == date_of_birth)

    async def get_by_user_id(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Tenant | None:
        return await self._first(db, self.model.user_id == user_id)


# Instantiate once — import this instance everywhere
tenant_repo = TenantRepository(Tenant)
