import uuid

from sqlalchemy import String, Text, Uuid, Boolean, Date, ForeignKey

from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base
from app.models.base import TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    current_address: Mapped[str] = mapped_column(String(500), nullable=False)
    date_of_birth: Mapped[Date] = mapped_column(Date, nullable=False)
    occupation: Mapped[str] = mapped_column(String(255), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    # Nullable + unique: a tenant can exist with no portal access yet.
    # Linked later via TenantService.link_user(); ondelete=SET NULL so a
    # deleted User account doesn't take the tenant's rental history with it.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} name={self.full_name} email={self.email}>"
