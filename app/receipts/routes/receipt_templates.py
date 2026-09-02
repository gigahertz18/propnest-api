from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_receipt_template_service, get_storage_client, require_manager_or_above
from app.db.session import get_db
from app.identity.models.user import User
from app.receipts.schemas.receipt_template import ReceiptTemplateResponse
from app.core.services.exceptions import ReceiptTemplateUploadError, ReceiptTemplateValidationError
from app.receipts.services.receipt_template_service import ReceiptTemplateService

router = APIRouter(prefix="/receipt-templates", tags=["Receipt Templates"])


@router.post(
    "/",
    response_model=ReceiptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_receipt_template(
    name: str = Form(...),
    property_id: UUID | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    receipt_template_service: ReceiptTemplateService = Depends(get_receipt_template_service),
    storage_client=Depends(get_storage_client),
):
    """Upload an HTML receipt template — `property_id` omitted (or null)
    uploads a candidate for the global default (ADMIN-only); a specific
    `property_id` uploads one scoped to that property (its manager or an
    admin). Uploading does not activate it — see the `/activate` route."""
    try:
        return await receipt_template_service.upload_template(
            db, name, property_id, current_user, storage_client=storage_client, file_obj=file
        )
    except (ReceiptTemplateUploadError, ReceiptTemplateValidationError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{template_id}/activate",
    response_model=ReceiptTemplateResponse,
)
async def activate_receipt_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    receipt_template_service: ReceiptTemplateService = Depends(get_receipt_template_service),
):
    """Make this the active template for its scope (a specific property, or
    the global default) — deactivates whichever template was previously
    active in that same scope, if any."""
    return await receipt_template_service.activate_template(db, template_id, current_user)


@router.get(
    "/",
    response_model=list[ReceiptTemplateResponse],
)
async def list_receipt_templates(
    property_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    receipt_template_service: ReceiptTemplateService = Depends(get_receipt_template_service),
):
    return await receipt_template_service.list_templates(db, current_user, property_id=property_id)


@router.get(
    "/{template_id}",
    response_model=ReceiptTemplateResponse,
)
async def get_receipt_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    receipt_template_service: ReceiptTemplateService = Depends(get_receipt_template_service),
):
    return await receipt_template_service.get_template(db, template_id, current_user)
