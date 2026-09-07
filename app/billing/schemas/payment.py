import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.billing.models.payment import PAYMENT_METHODS, PaymentStatus
from app.core.schemas.base import BaseResponse


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


# `cash` is exempt — it's auto-generated server-side (see
# PaymentService._resolve_reference_number) rather than format-checked here.
# `payment_method=None` is exempt too, matching today's fully-optional behavior.
# The third tuple element is the method's auto-prefix (e.g. "CHECK"), applied
# by PaymentService._resolve_reference_number to the raw core value validated
# here — this map validates only the unprefixed value the caller submits.
REFERENCE_NUMBER_FORMATS: dict[str, tuple[re.Pattern, str, str]] = {
    "check": (re.compile(r"^\d{4,10}$"), "must be 4-10 digits", "CHECK"),
    "gcash": (re.compile(r"^\d{13}$"), "must be exactly 13 digits", "GCASH"),
    "bank transfer": (
        re.compile(r"^[A-Za-z0-9-]{6,34}$"),
        "must be 6-34 alphanumeric characters or dashes",
        "TRANSFER",
    ),
    "maya": (re.compile(r"^[A-Za-z0-9-]{6,34}$"), "must be 6-34 alphanumeric characters or dashes", "MAYA"),
}


def _validate_reference_number_format(payment_method: str | None, reference_number: str | None) -> None:
    if payment_method not in REFERENCE_NUMBER_FORMATS:
        return
    pattern, message, _ = REFERENCE_NUMBER_FORMATS[payment_method]
    if not reference_number or not pattern.match(reference_number):
        raise ValueError(f"reference_number for payment_method '{payment_method}' {message}.")


def get_reference_number_prefix(payment_method: str | None) -> str | None:
    """The method's auto-prefix (e.g. 'CHECK'), or None if it doesn't get
    one. `cash` isn't in this map — its `CASH-` prefix is composed from a DB
    sequence in PaymentService._resolve_reference_number, not here."""
    entry = REFERENCE_NUMBER_FORMATS.get(payment_method)
    return entry[2] if entry else None


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

    @model_validator(mode="after")
    def validate_reference_number_format(self) -> "PaymentCreate":
        _validate_reference_number_format(self.payment_method, self.reference_number)
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
    def validate_reference_number_format(self) -> "PaymentUpdate":
        # Partial-update semantics: None means "leave unchanged," not "unset."
        # We can only format-check when the caller sets both fields together
        # in the same payload — checking a lone reference_number against an
        # existing row's payment_method would need a DB read, which schemas
        # don't have access to.
        if self.payment_method is not None and self.reference_number is not None:
            _validate_reference_number_format(self.payment_method, self.reference_number)
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
    def validate_reference_number_format(self) -> "PaymentCorrectionCreate":
        _validate_reference_number_format(self.payment_method, self.reference_number)
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
