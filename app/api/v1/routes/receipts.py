from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_receipt_service, get_storage_client, require_manager_or_above
from app.db.session import get_db
from app.models.user import User
from app.schemas.receipt import ReceiptResponse
from app.services.exceptions import ReceiptCreationError
from app.services.receipt_service import ReceiptService

router = APIRouter(tags=["Receipts"])


@router.post(
    "/payments/{payment_id}/receipts",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_receipt(
    payment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    receipt_service: ReceiptService = Depends(get_receipt_service),
    storage_client=Depends(get_storage_client),
):
    """Issue a receipt for `payment_id` — same operation whether this is the
    first receipt or a reprint (see ReceiptService.issue_receipt)."""
    try:
        return await receipt_service.issue_receipt(db, payment_id, current_user, storage_client=storage_client)
    except ReceiptCreationError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get(
    "/payments/{payment_id}/receipts",
    response_model=list[ReceiptResponse],
)
async def list_receipts_for_payment(
    payment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    receipt_service: ReceiptService = Depends(get_receipt_service),
):
    return await receipt_service.list_receipts_for_payment(db, payment_id, current_user)


@router.get(
    "/receipts/{receipt_id}",
    response_model=ReceiptResponse,
)
async def get_receipt(
    receipt_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    receipt_service: ReceiptService = Depends(get_receipt_service),
):
    return await receipt_service.get_receipt(db, receipt_id, current_user)


@router.get("/receipts/{receipt_id}/download")
async def download_receipt(
    receipt_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    receipt_service: ReceiptService = Depends(get_receipt_service),
    storage_client=Depends(get_storage_client),
):
    document, data = await receipt_service.get_receipt_document(db, receipt_id, current_user, storage_client)
    return Response(
        content=data,
        media_type=document.file_type,
        headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'},
    )
