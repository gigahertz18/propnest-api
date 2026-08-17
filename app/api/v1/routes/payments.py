import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import (
    get_payment_service,
    get_receipt_service,
    get_storage_client,
    require_manager_or_above,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.base import PaginatedResponse
from app.schemas.payment import PaymentCorrectionCreate, PaymentCreate, PaymentUpdate, PaymentResponse
from app.services.exceptions import PaymentAlreadyVoidedError
from app.services.payment_service import PaymentService
from app.services.receipt_service import ReceiptService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get(
    "/",
    response_model=PaginatedResponse[PaymentResponse],
)
async def list_payments(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    payment_service: PaymentService = Depends(get_payment_service),
    current_user: User = Depends(require_manager_or_above),
):
    """List payments."""
    return await payment_service.list_payments(db, current_user, skip=skip, limit=limit)


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
)
async def get_payment(
    payment_id: UUID,
    db: AsyncSession = Depends(get_db),
    payment_service: PaymentService = Depends(get_payment_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Get a single payment by ID."""
    return await payment_service.get_payment(db, payment_id, current_user)


@router.post(
    "/",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    payload: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    payment_service: PaymentService = Depends(get_payment_service),
    receipt_service: ReceiptService = Depends(get_receipt_service),
    storage_client=Depends(get_storage_client),
):
    """
    Record a new payment against a contract and automatically issue a receipt.

    Managers may only record payments for contracts on properties they're
    assigned to; admins can record for any contract. Receipt issuance
    failures are logged but do not fail this response — retry via
    POST /payments/{id}/receipts.
    """
    # Resource-level auth: managers may only record payments for
    # contracts on properties they are assigned to. Admins can record
    # payments for any contract.
    payment = await payment_service.create_payment(db, payload, current_user)

    # Receipt generation is decoupled from the payment's own commit: the
    # payment is already durably recorded above, so a PDF/storage failure
    # here must not fail this response — it's logged, and a client can
    # retry by calling POST /payments/{id}/receipts (the same "issue a
    # receipt" operation, whether first-time or reprint).
    try:
        await receipt_service.issue_receipt(db, payment.id, current_user, storage_client=storage_client)
    except Exception:
        logger.exception(f"Automatic receipt issuance failed for payment {payment.id}.")

    return payment


@router.patch(
    "/{payment_id}",
    response_model=PaymentResponse,
)
async def update_payment(
    payment_id: UUID,
    payload: PaymentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    payment_service: PaymentService = Depends(get_payment_service),
):
    """Update a payment. Fails with 409 if the payment has already been voided."""
    try:
        updated = await payment_service.update_payment(db, payment_id, payload, current_user)
    except PaymentAlreadyVoidedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Payment {payment_id} not found")
    return updated


@router.post(
    "/{payment_id}/corrections",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def correct_payment(
    payment_id: UUID,
    payload: PaymentCorrectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    payment_service: PaymentService = Depends(get_payment_service),
):
    """Void `payment_id` and create a replacement payment in its place —
    the append-only correction model (see PaymentService.void_and_correct_payment)."""
    try:
        return await payment_service.void_and_correct_payment(db, payment_id, payload, current_user)
    except PaymentAlreadyVoidedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.delete(
    "/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_payment(
    payment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    payment_service: PaymentService = Depends(get_payment_service),
) -> None:
    """Delete a payment."""
    await payment_service.delete_payment(db, payment_id, current_user)
