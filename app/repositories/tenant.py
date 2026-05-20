from datetime import date

from sqlalchemy.orm import Session

from app.repositories.base import BaseRepository
from app.models.tenants import Tenant
from app.schemas.tenants import TenantCreate, TenantUpdate


class TenantRepository(BaseRepository[Tenant, TenantCreate, TenantUpdate]):
    """
    Tenant-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    def get_by_email(
        self,
        db: Session,
        email: str,
    ) -> Tenant | None:
        return db.query(self.model).filter(self.model.email == email).first()

    def get_by_phone_number(
        self,
        db: Session,
        phone_number: str,
    ) -> Tenant | None:
        return db.query(self.model).filter(self.model.phone_number == phone_number).first()

    def get_by_full_name(
        self,
        db: Session,
        full_name: str,
    ) -> list[Tenant]:
        return db.query(self.model).filter(self.model.full_name.ilike(f"%{full_name}%")).all()

    def get_by_occupation(
        self,
        db: Session,
        occupation: str,
    ) -> list[Tenant]:
        return db.query(self.model).filter(self.model.occupation.ilike(f"%{occupation}%")).all()

    def get_by_date_of_birth(
        self,
        db: Session,
        date_of_birth: date,
    ) -> list[Tenant]:
        return db.query(self.model).filter(self.model.date_of_birth == date_of_birth).all()


# Instantiate once — import this instance everywhere
tenant_repo = TenantRepository(Tenant)
