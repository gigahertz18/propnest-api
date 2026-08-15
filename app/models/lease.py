import enum
import uuid

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Numeric, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class BillingCycle(str, enum.Enum):
    monthly = "monthly"


class RenewalOption(str, enum.Enum):
    auto = "auto"
    manual = "manual"
    none = "none"


class LeaseStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class Lease(Base, TimestampMixin):
    """
    Long-term-specific billing terms for a `Contract`, in a 1:1 relationship
    (enforced by `contract_id` being a unique FK). Only ever created against
    a `Contract` whose `rental_type` is `long_term` — `LeaseService` enforces
    this in application code, since a cross-table rental-type check can't be
    expressed as a DB constraint here.

    `due_day` (1-31): when a month has fewer days than `due_day` (e.g. 31 in
    February), the billing engine that consumes this field is expected to
    clamp to the last day of that month rather than skip a cycle.

    Late fee is modeled as two mutually-exclusive optional fields —
    `late_fee_amount` (flat) xor `late_fee_percent` — rather than picking one
    representation now, since the recurring-billing-engine issue (which
    actually applies the fee) has more context to decide which is used for
    a given lease; `ck_lease_late_fee_exactly_one` enforces exactly one is set.
    """

    __tablename__ = "leases"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("contracts.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
        nullable=False,
    )

    monthly_rent: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    due_day: Mapped[int] = mapped_column(nullable=False)

    billing_cycle: Mapped[BillingCycle] = mapped_column(
        Enum(BillingCycle, name="lease_billing_cycle_enum"),
        nullable=False,
        default=BillingCycle.monthly,
        server_default=text("'monthly'"),
    )

    security_deposit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    advance_payment: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    late_fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    late_fee_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    grace_period_days: Mapped[int] = mapped_column(nullable=False, default=0, server_default=text("0"))

    renewal_option: Mapped[RenewalOption] = mapped_column(
        Enum(RenewalOption, name="lease_renewal_option_enum"),
        nullable=False,
        default=RenewalOption.none,
        server_default=text("'none'"),
    )

    status: Mapped[LeaseStatus] = mapped_column(
        Enum(LeaseStatus, name="lease_status_enum"),
        nullable=False,
        default=LeaseStatus.ACTIVE,
        server_default=text("'ACTIVE'"),
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        CheckConstraint("monthly_rent > 0", name="ck_lease_monthly_rent_positive"),
        CheckConstraint("due_day >= 1 AND due_day <= 31", name="ck_lease_due_day_range"),
        CheckConstraint("security_deposit IS NULL OR security_deposit > 0", name="ck_lease_security_deposit_positive"),
        CheckConstraint("advance_payment IS NULL OR advance_payment > 0", name="ck_lease_advance_payment_positive"),
        CheckConstraint("grace_period_days >= 0", name="ck_lease_grace_period_days_nonnegative"),
        CheckConstraint(
            "(late_fee_amount IS NULL) <> (late_fee_percent IS NULL)", name="ck_lease_late_fee_exactly_one"
        ),
        CheckConstraint("late_fee_amount IS NULL OR late_fee_amount > 0", name="ck_lease_late_fee_amount_positive"),
        CheckConstraint(
            "late_fee_percent IS NULL OR (late_fee_percent > 0 AND late_fee_percent <= 100)",
            name="ck_lease_late_fee_percent_range",
        ),
        CheckConstraint("end_date IS NULL OR end_date > start_date", name="ck_lease_dates"),
    )

    def __repr__(self) -> str:
        return f"<Lease id={self.id} contract_id={self.contract_id} status={self.status}>"
