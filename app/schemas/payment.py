import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.payment import PAYMENT_METHODS, PaymentStatus
from app.schemas.base import BaseResponse


# ─── Helper ─────────────────────────────────────────────────
def _normalize_payment_method(value: str | None) -> str | None:
    """Validates payment_method case-insensitively and return its canonical
    lowercase form, so no variant casing can reach the DB's case-sensitive ck_payment_method
    CHECK constraint (see payment-method-casing-mismatch)"""
    if value is None:
        return None
    if value.lower() not in PAYMENT_METHODS:
        raise ValueError(f"Invalid payment_method '{value}'. Must be one of {PAYMENT_METHODS}.")
    return value.lower()


# ─── Base ─────────────────────────────────────────────────
class PaymentBase(BaseModel):
    contract_id: uuid.UUID
    billing_record_id: uuid.UUID | None = Field(
        default=None,
        description="Optional link to the billing record this payment settles.",
    )
    amount: Decimal = Field(gt=0, description="Must be greater than zero.")
    paid_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payment_method: str | None = None
    status: PaymentStatus = PaymentStatus.PAID
    reference_number: str | None = None


# ─── Create ───────────────────────────────────────────────
class PaymentCreate(PaymentBase):
    """Used when creating a new payment — request body."""

    @model_validator(mode="after")
    def validate_payment_method(self) -> "PaymentCreate":
        self.payment_method = _normalize_payment_method(self.payment_method)
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
    status: PaymentStatus | None = None
    reference_number: str | None = None

    @model_validator(mode="after")
    def validate_payment_method(self) -> "PaymentUpdate":
        self.payment_method = _normalize_payment_method(self.payment_method)
        return self

    @model_validator(mode="after")
    def validate_status_not_voided(self) -> "PaymentUpdate":
        if self.status == PaymentStatus.VOIDED:
            raise ValueError("status cannot be set to VOIDED directly; use the payment correction endpoint instead.")
        return self


# ─── Correction ───────────────────────────────────────────
class PaymentCorrectionCreate(BaseModel):
    """Body for POST /payments/{id}/corrections.

    Creates a new payment row that replaces a mis-entered one; the
    original is voided rather than mutated (see
    `PaymentService.void_and_correct_payment`). `contract_id` is
    intentionally absent — the correction always inherits the contract
    of the payment it corrects.
    """

    amount: Decimal = Field(gt=0, description="Must be greater than zero.")
    paid_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payment_method: str | None = None
    status: PaymentStatus = PaymentStatus.PAID
    reference_number: str | None = None

    @model_validator(mode="after")
    def validate_payment_method(self) -> "PaymentCorrectionCreate":
        self.payment_method = _normalize_payment_method(self.payment_method)
        return self

    @model_validator(mode="after")
    def validate_status_not_voided(self) -> "PaymentCorrectionCreate":
        if self.status == PaymentStatus.VOIDED:
            raise ValueError("A correction can't be created as VOIDED — it must start out as an active payment.")
        return self


# ─── Response ─────────────────────────────────────────────
class PaymentResponse(PaymentBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    corrects_payment_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
