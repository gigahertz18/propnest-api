import calendar
import enum
import uuid

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, Enum, ForeignKey, Numeric, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class BillingRecordStatus(str, enum.Enum):
    pending = "pending"
    partially_paid = "partially_paid"
    paid = "paid"
    overdue = "overdue"
    written_off = "written_off"


def last_day_of_month(any_day: date) -> date:
    """Return the last calendar day of `any_day`'s month — shared by
    `LeaseBillingService` for computing `period_end`/clamped `due_date`."""
    return date(any_day.year, any_day.month, calendar.monthrange(any_day.year, any_day.month)[1])


class BillingRecord(Base, TimestampMixin):
    """
    One charge for a single `Lease` in a single billing period, generated
    manually (no cron — see recurring-billing-engine's scope) by
    `LeaseBillingService`. Long-term-specific by design, mirroring `Lease`
    itself: a future short-term `BookingBillingRecord` is expected to be its
    own model rather than a `rental_type` branch grafted onto this one.

    `amount_due` and `due_date` are snapshotted at generation time rather
    than derived live from `Lease` on every read, so a later edit to
    `Lease.monthly_rent`/`due_day` doesn't retroactively rewrite already-
    generated billing history.

    `late_fee_amount_charged` is tracked separately from `amount_due` rather
    than folded into it — a future reconciliation issue can compute
    `amount_due + late_fee_amount_charged` without this issue needing to
    pre-compute a "total owed" figure that Payment-linkage doesn't need yet.
    """

    __tablename__ = "billing_records"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    lease_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("leases.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    late_fee_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    late_fee_amount_charged: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Set by `LeaseBillingService.apply_payment` when cumulative payments
    # exceed `amount_due + late_fee_amount_charged` — the record still
    # transitions to `paid` rather than rejecting the payment; this is
    # where the excess is surfaced for later Dashboard/Accounting use.
    overpaid_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    status: Mapped[BillingRecordStatus] = mapped_column(
        Enum(BillingRecordStatus, name="billing_record_status_enum"),
        nullable=False,
        default=BillingRecordStatus.pending,
        server_default=text("'pending'"),
    )

    __table_args__ = (
        UniqueConstraint("lease_id", "period_start", name="uq_billing_record_lease_id_period_start"),
        CheckConstraint("amount_due > 0", name="ck_billing_record_amount_due_positive"),
        CheckConstraint(
            "late_fee_amount_charged IS NULL OR late_fee_amount_charged > 0",
            name="ck_billing_record_late_fee_amount_positive",
        ),
        CheckConstraint(
            "overpaid_amount IS NULL OR overpaid_amount > 0",
            name="ck_billing_record_overpaid_amount_positive",
        ),
        CheckConstraint(
            "(late_fee_applied = false AND late_fee_amount_charged IS NULL) "
            "OR (late_fee_applied = true AND late_fee_amount_charged IS NOT NULL)",
            name="ck_billing_record_late_fee_consistency",
        ),
        CheckConstraint("period_end > period_start", name="ck_billing_record_period_dates"),
        CheckConstraint("due_date >= period_start", name="ck_billing_record_due_date_after_period_start"),
    )

    def __repr__(self) -> str:
        return f"<BillingRecord id={self.id} lease_id={self.lease_id} period_start={self.period_start} status={self.status}>"
