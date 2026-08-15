import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, model_validator, Field

from app.schemas.base import BaseResponse
from app.models.lease import BillingCycle, RenewalOption, LeaseStatus


def _validate_dates_and_late_fee(end_date, start_date, late_fee_amount, late_fee_percent):
    if end_date and start_date and end_date <= start_date:
        raise ValueError("end_date must be after start_date.")

    if (late_fee_amount is None) == (late_fee_percent is None):
        raise ValueError("Exactly one of late_fee_amount or late_fee_percent must be set.")


# ─── Base ─────────────────────────────────────────────────
class LeaseBase(BaseModel):
    contract_id: uuid.UUID
    monthly_rent: Decimal = Field(gt=0, description="Must be greater than zero.")
    due_day: int = Field(ge=1, le=31)
    billing_cycle: BillingCycle = BillingCycle.monthly
    security_deposit: Decimal | None = Field(default=None, gt=0, description="Must be greater than 0 if provided.")
    advance_payment: Decimal | None = Field(default=None, gt=0, description="Must be greater than 0 if provided.")
    late_fee_amount: Decimal | None = Field(default=None, gt=0, description="Must be greater than 0 if provided.")
    late_fee_percent: Decimal | None = Field(
        default=None, gt=0, le=100, description="Must be between 0 (exclusive) and 100 if provided."
    )
    grace_period_days: int = Field(default=0, ge=0)
    renewal_option: RenewalOption = RenewalOption.none
    status: LeaseStatus = LeaseStatus.ACTIVE
    start_date: date
    end_date: date | None = None


# ─── Create ───────────────────────────────────────────────
class LeaseCreate(LeaseBase):
    """Used when creating a new lease — request body."""

    @model_validator(mode="after")
    def validate_dates_and_late_fee(self) -> "LeaseCreate":
        _validate_dates_and_late_fee(self.end_date, self.start_date, self.late_fee_amount, self.late_fee_percent)
        return self


# ─── Update ───────────────────────────────────────────────
class LeaseUpdate(BaseModel):
    """All fields optional — only send what you want to change.

    `contract_id` is intentionally absent: a lease's owning contract is
    fixed at creation, mirroring `ContractUpdate`'s immutable `property_id`.
    """

    monthly_rent: Decimal | None = Field(default=None, gt=0, description="Must be greater than zero.")
    due_day: int | None = Field(default=None, ge=1, le=31)
    billing_cycle: BillingCycle | None = None
    security_deposit: Decimal | None = Field(default=None, gt=0, description="Must be greater than 0 if provided.")
    advance_payment: Decimal | None = Field(default=None, gt=0, description="Must be greater than 0 if provided.")
    late_fee_amount: Decimal | None = Field(default=None, gt=0, description="Must be greater than 0 if provided.")
    late_fee_percent: Decimal | None = Field(
        default=None, gt=0, le=100, description="Must be between 0 (exclusive) and 100 if provided."
    )
    grace_period_days: int | None = Field(default=None, ge=0)
    renewal_option: RenewalOption | None = None
    status: LeaseStatus | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates_and_late_fee(self) -> "LeaseUpdate":
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date.")

        if self.late_fee_amount is not None and self.late_fee_percent is not None:
            raise ValueError("Only one of late_fee_amount or late_fee_percent may be set.")

        return self


# ─── Response ─────────────────────────────────────────────
class LeaseResponse(LeaseBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
