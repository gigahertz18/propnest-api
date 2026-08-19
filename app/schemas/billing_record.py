import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

from app.schemas.base import BaseResponse
from app.models.billing_record import BillingRecordStatus


# ─── Base ─────────────────────────────────────────────────
class BillingRecordBase(BaseModel):
    lease_id: uuid.UUID
    period_start: date
    period_end: date
    due_date: date
    amount_due: Decimal = Field(gt=0, description="Must be greater than zero.")
    late_fee_applied: bool = False
    late_fee_amount_charged: Decimal | None = Field(
        default=None, gt=0, description="Must be greater than 0 if provided."
    )
    status: BillingRecordStatus = BillingRecordStatus.pending


# ─── Create ───────────────────────────────────────────────
class BillingRecordCreate(BillingRecordBase):
    """
    Used internally by `LeaseBillingService.generate_billing_record`, which
    computes `period_end`/`due_date`/`amount_due` itself — not a route
    request body (see `BillingRecordGenerateRequest` for that).
    """

    pass


# ─── Update ───────────────────────────────────────────────
class BillingRecordUpdate(BaseModel):
    """
    All fields optional. No route in this issue exposes a partial update —
    this exists to satisfy `BaseRepository`'s generic Create/Update typevars.
    """

    status: BillingRecordStatus | None = None
    late_fee_applied: bool | None = None
    late_fee_amount_charged: Decimal | None = Field(
        default=None, gt=0, description="Must be greater than 0 if provided."
    )


# ─── Response ─────────────────────────────────────────────
class BillingRecordResponse(BillingRecordBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    overpaid_amount: Decimal | None = None
    created_at: datetime
    updated_at: datetime


# ─── Route-only request bodies ───────────────────────────
class BillingRecordGenerateRequest(BaseModel):
    """
    Request body for `POST /billing-records/generate`. Deliberately narrower
    than `BillingRecordCreate` — a caller supplies only `lease_id` and
    `period_start`; the service computes `period_end`/`due_date`/
    `amount_due`/`status` itself so a client can't spoof them.
    """

    lease_id: uuid.UUID
    period_start: date


class BillingRecordLateFeeCorrection(BaseModel):
    """
    Request body for `PATCH /billing-records/{id}/late-fee`. Deliberately narrower
    than `BillingRecordUpdate` - `status` isn't correctable here (see `write_off_billing_record`
    for the one status transition exposed to the API). Both fields are required together so
    the payload always states a comlete, self-consistent late-fee position rather than
    patching one field and leaving the other stale.
    """

    late_fee_applied: bool
    late_fee_amount_charged: Decimal | None = Field(
        default=None,
        gt=0,
        description="Must be greater than 0 if provided.",
    )

    @model_validator(mode="after")
    def validate_consistency(self) -> "BillingRecordLateFeeCorrection":
        """Mirrors `ck_billing_record_late_fee_consistency` at the schema
        layer so a bad combination fails fast with a 422, instead of surfacing
        as an opaque 409 from the DB constraint."""

        if self.late_fee_applied and self.late_fee_amount_charged is None:
            raise ValueError("late_fee_amount_charged is required when late_fee_applied is True")
        if not self.late_fee_applied and self.late_fee_amount_charged is not None:
            raise ValueError("late_fee_amount_charged must be omitted when late_fee_applied is False")

        return self
