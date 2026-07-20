import enum
import uuid

from app.db.constraints import sql_in_clause
from app.db.session import Base
from app.models.base import TimestampMixin
from datetime import date
from decimal import Decimal

from sqlalchemy import String, ForeignKey, Date, Uuid, Enum, CheckConstraint, Index, text, Numeric
from sqlalchemy.orm import Mapped, mapped_column


class RentalType(str, enum.Enum):
    long_term = "long_term"
    short_term = "short_term"


class BookingSource(str, enum.Enum):
    direct = "direct"
    airbnb = "airbnb"
    booking = "booking"
    agoda = "agoda"


# Backwards-compatible tuple used by schema validation/tests
BOOKING_SOURCE = tuple(bs.value for bs in BookingSource)


class ContractStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class Contract(Base, TimestampMixin):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("properties.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    rental_type: Mapped[RentalType] = mapped_column(
        Enum(RentalType, name="rental_type_enum"),
        nullable=False,
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    rent_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    deposit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    booking_source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="direct",
        server_default=text("'direct'"),
    )

    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=ContractStatus.ACTIVE.value,
        server_default=text("'ACTIVE'"),
    )

    __table_args__ = (
        # Ensure booking_source is one of the accepted platforms.
        CheckConstraint(
            sql_in_clause("booking_source", BOOKING_SOURCE),
            name="ck_contract_booking_source",
        ),
        # Dates: end_date must be strictly after start_date when provided.
        CheckConstraint(
            "end_date IS NULL OR end_date > start_date",
            name="ck_contract_dates",
        ),
        # Monetary values must be greater than zero.
        CheckConstraint("rent_amount > 0", name="ck_contract_rent_positive"),
        CheckConstraint("deposit IS NULL OR deposit > 0", name="ck_contract_deposit_positive"),
        # Ensure at most one ACTIVE contract exists per property at the DB level.
        # This is a partial unique index on property_id where status = 'ACTIVE'.
        Index("uq_active_contract_property", "property_id", unique=True, postgresql_where=text("status = 'ACTIVE'")),
    )

    def __repr__(self) -> str:
        return f"<Contract id={self.id} property_id={self.property_id} tenant_id={self.tenant_id}>"
