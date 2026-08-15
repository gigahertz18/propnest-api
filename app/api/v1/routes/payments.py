from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_payment_service, require_manager_or_above
from app.db.session import get_db
from app.models.user import User
from app.schemas.base import PaginatedResponse
from app.schemas.payment import PaymentCorrectionCreate, PaymentCreate, PaymentUpdate, PaymentResponse
from app.services.exceptions import PaymentAlreadyVoidedError
from app.services.payment_service import PaymentService

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
):
    # Resource-level auth: managers may only record payments for
    # contracts on properties they are assigned to. Admins can record
    # payments for any contract.
    return await payment_service.create_payment(db, payload, current_user)


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
    await payment_service.delete_payment(db, payment_id, current_user)
