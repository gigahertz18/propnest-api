import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, model_validator, Field

from app.schemas.base import BaseResponse
from app.models.contract import RentalType, BOOKING_SOURCE


# ─── Base ─────────────────────────────────────────────────
class ContractBase(BaseModel):
    property_id: uuid.UUID
    tenant_id: uuid.UUID
    rental_type: RentalType
    start_date: date
    end_date: date | None = None
    rent_amount: Decimal = Field(gt=0, description="Must be greater than zero.")
    deposit: Decimal | None = Field(default=None, gt=0, description="Must be greater than 0 if provided.")
    booking_source: str = "direct"
    status: str = "ACTIVE"


# ─── Create ───────────────────────────────────────────────
class ContractCreate(ContractBase):
    """Used when creating a new contract — request body."""

    @model_validator(mode="after")
    def validate_dates_and_booking_source(self) -> "ContractCreate":
        if self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date.")

        if self.booking_source not in BOOKING_SOURCE:
            raise ValueError(f"Invalid booking_source '{self.booking_source}'. " f"Must be one of: {BOOKING_SOURCE}.")

        return self


# ─── Update ───────────────────────────────────────────────
class ContractUpdate(BaseModel):
    """All fields optional — only send what you want to change."""

    rental_type: RentalType | None = None
    start_date: date | None = None
    end_date: date | None = None
    rent_amount: Decimal | None = Field(default=None, gt=0, description="Must be greater than zero.")
    deposit: Decimal | None = Field(default=None, gt=0, description="Must be greater than zero if provided.")
    booking_source: str | None = None
    status: str | None = None

    @model_validator(mode="after")
    def validate_dates_and_booking_source(self) -> "ContractUpdate":
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date.")

        if self.booking_source and self.booking_source not in BOOKING_SOURCE:
            raise ValueError(f"Invalid booking_source '{self.booking_source}'. " f"Must be one of: {BOOKING_SOURCE}.")

        return self


# ─── Response ─────────────────────────────────────────────
class ContractResponse(ContractBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
