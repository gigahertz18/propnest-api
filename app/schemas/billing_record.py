import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field

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
    Request body for `POST /billing-records/generate`. A caller supplies
    only `lease_id` — `period_start` is derived server-side from
    `lease.start_date` (or the prior generated period's `period_end`) so
    periods are always contiguous and never precede the lease's actual
    start date; `period_end`/`due_date`/`amount_due`/`status` are then
    computed from that, same as before.
    """

    lease_id: uuid.UUID
