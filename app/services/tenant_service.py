from datetime import date
from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.tenant import TenantRepository
from app.schemas.tenant import TenantCreate, TenantUpdate
from app.models.tenant import Tenant


class TenantService:
    """Business logic for `Tenant` entities."""

    def __init__(self, tenant_repo: TenantRepository) -> None:
        self.tenant_repo = tenant_repo

    def list_tenants(self, db: Session, skip: int = 0, limit: int = 100) -> list[Tenant]:
        return self.tenant_repo.get_all(db, skip=skip, limit=limit)

    def get_tenant(self, db: Session, id: UUID) -> Tenant | None:
        return self.tenant_repo.get_by_id(db, id)

    def create_tenant(self, db: Session, payload: TenantCreate) -> Tenant:
        return self.tenant_repo.create(db, payload)

    def update_tenant(self, db: Session, id: UUID, payload: TenantUpdate) -> Tenant | None:
        return self.tenant_repo.update(db, id, payload)

    def delete_tenant(self, db: Session, id: UUID) -> Tenant | None:
        return self.tenant_repo.delete(db, id)

    def get_by_email(self, db: Session, email: str) -> Tenant | None:
        return self.tenant_repo.get_by_email(db, email)

    def get_by_phone_number(self, db: Session, phone_number: str) -> Tenant | None:
        return self.tenant_repo.get_by_phone_number(db, phone_number)

    def get_by_full_name(self, db: Session, full_name: str) -> list[Tenant]:
        return self.tenant_repo.get_by_full_name(db, full_name)

    def get_by_occupation(self, db: Session, occupation: str) -> list[Tenant]:
        return self.tenant_repo.get_by_occupation(db, occupation)

    def get_by_date_of_birth(self, db: Session, date_of_birth: date) -> list[Tenant]:
        return self.tenant_repo.get_by_date_of_birth(db, date_of_birth)
