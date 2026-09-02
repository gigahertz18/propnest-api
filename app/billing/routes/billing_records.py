from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_lease_billing_service, require_manager_or_above
from app.db.session import get_db
from app.identity.models.user import User
from app.core.schemas.base import PaginatedResponse
from app.billing.schemas.billing_record import (
    BillingRecordGenerateRequest,
    BillingRecordLateFeeCorrection,
    BillingRecordResponse,
)
from app.billing.services.lease_billing_service import LeaseBillingService
from app.core.services.exceptions import (
    BillingRecordAlreadyGeneratedError,
    BillingRecordCorrectionNotAllowedError,
    InvalidBillingRecordTransitionError,
)

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

    period_start/period_end/due_date/amount_due are all computed server-side
    from the lease's terms — the caller only supplies lease_id. Fails with
    409 if a record for the resulting period already exists (a concurrent
    duplicate request).
    """
    try:
        return await billing_service.generate_billing_record(db, payload.lease_id, current_user)
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


@router.post(
    "/{billing_record_id}/write-off",
    response_model=BillingRecordResponse,
)
async def write_off_billing_record(
    billing_record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    billing_service: LeaseBillingService = Depends(get_lease_billing_service),
):
    """
    Write off a billing record — the only state-machine-valid path to
    `written_off`. Fails with 409 if the record's current status doesn't
    permit this transition (see LeaseBillingService._VALID_TRANSITIONS).
    """
    try:
        return await billing_service.write_off_billing_record(db, billing_record_id, current_user)
    except InvalidBillingRecordTransitionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.patch(
    "/{billing_record_id}/late-fee",
    response_model=BillingRecordResponse,
)
async def correct_late_fee(
    billing_record_id: UUID,
    payload: BillingRecordLateFeeCorrection,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    billing_service: LeaseBillingService = Depends(get_lease_billing_service),
):
    """
    Correct a billing record's late-fee fields (e.g. to reverse an
    erroneous overdue evaluation). Only allowed while the record is
    non-terminal; fails with 409 once it's `paid`/`written_off`.
    """
    try:
        return await billing_service.correct_late_fee(db, billing_record_id, payload, current_user)
    except BillingRecordCorrectionNotAllowedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
