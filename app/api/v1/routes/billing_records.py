from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_lease_billing_service, require_manager_or_above
from app.db.session import get_db
from app.models.user import User
from app.schemas.base import PaginatedResponse
from app.schemas.billing_record import BillingRecordGenerateRequest, BillingRecordResponse
from app.services.lease_billing_service import LeaseBillingService
from app.services.exceptions import BillingRecordAlreadyGeneratedError

router = APIRouter(prefix="/billing-records", tags=["Billing Records"])


@router.get(
    "/",
    response_model=PaginatedResponse[BillingRecordResponse],
)
async def list_billing_records(
    lease_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    billing_service: LeaseBillingService = Depends(get_lease_billing_service),
):
    """List billing records for a lease."""
    return await billing_service.list_for_lease(db, lease_id, current_user, skip=skip, limit=limit)


@router.get(
    "/{billing_record_id}",
    response_model=BillingRecordResponse,
)
async def get_billing_record(
    billing_record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    billing_service: LeaseBillingService = Depends(get_lease_billing_service),
):
    """Get a single billing record by ID."""
    return await billing_service.get_billing_record(db, billing_record_id, current_user)


@router.post(
    "/generate",
    response_model=BillingRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_billing_record(
    payload: BillingRecordGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    billing_service: LeaseBillingService = Depends(get_lease_billing_service),
):
    """
    Generate the billing record for a lease's next period.

    period_end/due_date/amount_due are computed server-side from the lease's
    terms — callers only supply lease_id and period_start. Fails with 409 if
    a record for that period already exists.
    """
    try:
        return await billing_service.generate_billing_record(db, payload.lease_id, payload.period_start, current_user)
    except BillingRecordAlreadyGeneratedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post(
    "/{billing_record_id}/evaluate-overdue",
    response_model=BillingRecordResponse,
)
async def evaluate_overdue(
    billing_record_id: UUID,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    billing_service: LeaseBillingService = Depends(get_lease_billing_service),
):
    """Re-evaluate a billing record's overdue status as of a given date (defaults to today)."""
    return await billing_service.evaluate_overdue(db, billing_record_id, current_user, as_of=as_of)
