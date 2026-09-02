import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric, DateTime, String, Uuid, CheckConstraint, Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.constraints import sql_in_clause
from app.db.session import Base
from app.core.models.base import TimestampMixin

# Listing platforms as a constant — easy to extend without a native enum migration
PAYMENT_METHODS = ("cash", "bank transfer", "gcash", "maya", "check")


class PaymentStatus(str, enum.Enum):
    PAID = "PAID"
    PENDING = "PENDING"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)

    # Additive to contract_id, not a replacement — see PaymentRepository's
    # manager-scoping join, which still resolves through contract_id.
    billing_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_records.id"), nullable=True, index=True
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    payment_method: Mapped[str] = mapped_column(
        String(50),
        nullable=True,
    )

    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status_enum"),
        nullable=False,
        default=PaymentStatus.PAID,
    )

    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Append-only correction model: correcting a payment never mutates it in
    # place (a receipt may already reference its id) — instead the original
    # is marked VOIDED and a new row is created pointing back here.
    corrects_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            sql_in_clause("payment_method", PAYMENT_METHODS),
            name="ck_payment_method",
        ),
    )

    def __repr__(self) -> str:
        return f"<Payment id={self.id} contract_id={self.contract_id} amount={self.amount} status={self.status}>"
