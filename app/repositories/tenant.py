import uuid

from collections.abc import Sequence
from datetime import date
from sqlalchemy import select, exists, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.tenant import Tenant
from app.models.contract import Contract
from app.models.property import Property
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
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Tenant]:

        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        return await self._all(
            db,
            self.model.full_name.ilike(f"%{full_name}%"),
            offset=skip,
            limit=limit,
        )

    async def get_by_occupation(
        self,
        db: AsyncSession,
        occupation: str,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Tenant]:
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        return await self._all(
            db,
            self.model.occupation.ilike(f"%{occupation}%"),
            offset=skip,
            limit=limit,
        )

    async def get_by_date_of_birth(
        self,
        db: AsyncSession,
        date_of_birth: date,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Tenant]:
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        return await self._all(
            db,
            self.model.date_of_birth == date_of_birth,
            offset=skip,
            limit=limit,
        )

    async def get_by_user_id(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Tenant | None:
        return await self._first(db, self.model.user_id == user_id)

    def _accessible_by_manager_clause(self, manager_id: uuid.UUID):
        """
        A tenant is visible/actionable by a manager if either:
        - the tenant has no contracts at all yet (unclaimed — any manager
          may act on a tenant nobody has attached to a property yet), or
        - at least one of the tenant's contracts is for a property that
          manager owns.

        Built with correlated EXISTS subqueries rather than a join, so a
        tenant with multiple contracts across different properties
        doesn't produce duplicate rows that need a `.distinct()` to
        paper over.
        """
        has_any_contract = exists().where(Contract.tenant_id == self.model.id)
        has_owned_contract = exists().where(
            Contract.tenant_id == self.model.id,
            Contract.property_id == Property.id,
            Property.manager_id == manager_id,
        )
        return or_(~has_any_contract, has_owned_contract)

    async def get_all_for_manager(
        self,
        db: AsyncSession,
        manager_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Tenant]:
        """Tenants a manager may list: unclaimed tenants (no contract yet)
        plus tenants tied to at least one of the manager's own properties."""
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        stmt = (
            select(self.model)
            .where(self._accessible_by_manager_clause(manager_id))
            .order_by(self.model.created_at)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def is_accessible_by_manager(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        manager_id: uuid.UUID,
    ) -> bool:
        """Single-tenant version of `get_all_for_manager`'s rule, used to
        authorize get/update/delete/link operations on one tenant."""
        stmt = select(self.model.id).where(
            self.model.id == tenant_id,
            self._accessible_by_manager_clause(manager_id),
        )
        result = await db.execute(stmt)
        return result.scalar() is not None


# Instantiate once — import this instance everywhere
tenant_repo = TenantRepository(Tenant)
