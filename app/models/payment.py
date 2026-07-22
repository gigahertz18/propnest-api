import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric, DateTime, String, Uuid, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.constraints import sql_in_clause
from app.db.session import Base
from app.models.base import TimestampMixin

# Listing platforms as a constant — easy to extend without a native enum migration
PAYMENT_METHODS = ("cash", "bank transfer", "gcash", "maya")


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)

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

    status: Mapped[str] = mapped_column(String(10), default="PAID")

    __table_args__ = (
        CheckConstraint(
            sql_in_clause("payment_method", PAYMENT_METHODS),
            name="ck_payment_method",
        ),
    )

    def __repr__(self) -> str:
        return f"<Payment id={self.id} contract_id={self.contract_id} amount={self.amount} status={self.status}>"
