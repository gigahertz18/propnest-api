from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_payment_service, require_manager_or_above
from app.db.session import get_db
from app.models.user import User
from app.schemas.base import PaginatedResponse
from app.schemas.payment import PaymentCreate, PaymentUpdate, PaymentResponse
from app.services.payment_service import PaymentService
from app.services.exceptions import PaymentForbiddenError, RelatedResourceNotFoundError

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
    try:
        return await payment_service.get_payment(db, payment_id, current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PaymentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


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
    try:
        # Resource-level auth: managers may only record payments for
        # contracts on properties they are assigned to. Admins can record
        # payments for any contract.
        return await payment_service.create_payment(db, payload, current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PaymentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


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
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PaymentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Payment {payment_id} not found")
    return updated


@router.delete(
    "/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_payment(
    payment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    payment_service: PaymentService = Depends(get_payment_service),
):
    try:
        return await payment_service.delete_payment(db, payment_id, current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PaymentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
