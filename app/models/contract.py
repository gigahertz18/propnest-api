import enum
import uuid
from sqlalchemy import String, ForeignKey, Date, Numeric, Uuid, Enum, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base
from app.models.base import TimestampMixin


class RentalType(str, enum.Enum):
    long_term = "long_term"
    short_term = "short_term"


# Listing platforms as a constant — easy to extend without a native enum migration
BOOKING_SOURCE = ("direct", "airbnb", "booking", "agoda")


class Contract(Base, TimestampMixin):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), index=True)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    rental_type: Mapped[RentalType] = mapped_column(
        Enum(RentalType),
        nullable=False,
    )

    start_date: Mapped[Date] = mapped_column(Date)
    end_date: Mapped[Date | None] = mapped_column(Date, nullable=True)

    rent_amount: Mapped[float] = mapped_column(Numeric(12, 2))

    deposit: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    booking_source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="direct",
    )

    status: Mapped[str] = mapped_column(String, default="ACTIVE")

    __table_args__ = (
        CheckConstraint(
            f"booking_source IN {BOOKING_SOURCE}",
            name="ck_contract_booking_source",
        ),
    )

    def __repr__(self) -> str:
        return f"<Contract id={self.id} property_id={self.property_id} tenant_id={self.tenant_id}>"
