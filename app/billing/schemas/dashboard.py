from decimal import Decimal

from pydantic import BaseModel

from app.billing.schemas.billing_record import BillingRecordResponse
from app.leasing.schemas.lease import LeaseResponse
from app.billing.schemas.payment import PaymentResponse


class DashboardSummaryResponse(BaseModel):
    """Composed response for the landlord dashboard — seven independently
    computed figures, not derived from a single ORM object."""

    collected_this_month: Decimal
    outstanding: Decimal
    total_credits: Decimal
    late_payments: list[BillingRecordResponse]
    vacant_units: int
    expiring_leases: list[LeaseResponse]
    recent_payments: list[PaymentResponse]
