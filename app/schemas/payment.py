import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.payment import PAYMENT_METHODS
from app.schemas.base import BaseResponse


# ─── Base ─────────────────────────────────────────────────
class PaymentBase(BaseModel):
    contract_id: uuid.UUID
    amount: Decimal = Field(gt=0, description="Must be greater than zero.")
    paid_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payment_method: str | None = None
    status: str = "PAID"


# ─── Create ───────────────────────────────────────────────
class PaymentCreate(PaymentBase):
    """Used when creating a new payment — request body."""

    @model_validator(mode="after")
    def validate_payment_method(self) -> "PaymentCreate":
        if self.payment_method is not None and self.payment_method not in PAYMENT_METHODS:
            raise ValueError(f"Invalid payment_method '{self.payment_method}'. Must be one of: {PAYMENT_METHODS}.")
        return self


# ─── Update ───────────────────────────────────────────────
class PaymentUpdate(BaseModel):
    """All fields optional — only send what you want to change.

    `contract_id` is intentionally absent: a payment can't be relinked to a
    different contract, matching how `ContractUpdate` never lets `property_id`
    change after creation.
    """

    amount: Decimal | None = Field(default=None, gt=0, description="Must be greater than zero.")
    paid_at: datetime | None = None
    payment_method: str | None = None
    status: str | None = None

    @model_validator(mode="after")
    def validate_payment_method(self) -> "PaymentUpdate":
        if self.payment_method is not None and self.payment_method not in PAYMENT_METHODS:
            raise ValueError(f"Invalid payment_method '{self.payment_method}'. Must be one of: {PAYMENT_METHODS}.")
        return self


# ─── Response ─────────────────────────────────────────────
class PaymentResponse(PaymentBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
