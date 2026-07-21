from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import (
    get_document_service,
    require_manager_or_above,
    get_storage_client,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.base import PaginatedResponse
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate, DocumentResponse
from app.services.document_service import DocumentService
from app.services.exceptions import (
    DocumentDeletionError,
    DocumentUploadError,
    RelatedResourceNotFoundError,
    DocumentForbiddenError,
)

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get(
    "/",
    response_model=PaginatedResponse[DocumentResponse],
)
async def list_documents(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
    current_user: User = Depends(require_manager_or_above),
):
    return await document_service.list_documents(db, current_user, skip=skip, limit=limit)


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
    current_user: User = Depends(require_manager_or_above),
):
    try:
        return await document_service.get_document(db, document_id, current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DocumentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    payload: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_manager_or_above),
    document_service: DocumentService = Depends(get_document_service),
):
    try:
        return await document_service.create_document(db, payload, current_user=current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DocumentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile = File(...),
    file_type: str = Form(...),
    contract_id: UUID | None = Form(None),
    property_id: UUID | None = Form(None),
    tenant_id: UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
    storage_client=Depends(get_storage_client),
    current_user: object = Depends(require_manager_or_above),
    document_service: DocumentService = Depends(get_document_service),
):
    """Accept multipart/form uploads and stream directly to storage.

    This endpoint keeps metadata in sync with the storage object.
    """
    payload = DocumentCreate(
        file_name=file.filename,
        file_type=file_type,
        contract_id=contract_id,
        property_id=property_id,
        tenant_id=tenant_id,
    )

    try:
        return await document_service.create_document(
            db,
            payload,
            storage_client=storage_client,
            file_obj=file,
            current_user=current_user,
        )
    except DocumentUploadError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to store document")
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DocumentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put(
    "/{document_id}/file",
    response_model=DocumentResponse,
)
async def replace_document_file(
    document_id: UUID,
    file: UploadFile = File(...),
    file_type: str = Form(...),
    contract_id: UUID | None = Form(None),
    property_id: UUID | None = Form(None),
    tenant_id: UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
    storage_client=Depends(get_storage_client),
    current_user: object = Depends(require_manager_or_above),
    document_service: DocumentService = Depends(get_document_service),
):
    """Replace the physical file behind an existing document, optionally
    relinking it to a different property/contract/tenant in the same
    request. This is the only correct way to change a document's file —
    PATCH /{document_id} is relink-only and cannot touch storage.
    """

    # This payload is the new file to be stored, not the existing document.
    payload = DocumentFileUpdate(
        file_name=file.filename,
        file_type=file_type,
        contract_id=contract_id,
        property_id=property_id,
        tenant_id=tenant_id,
    )

    try:
        updated = await document_service.replace_document_file(
            db,
            document_id,
            payload,
            file_obj=file,
            storage_client=storage_client,
            current_user=current_user,
        )
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DocumentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except DocumentUploadError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to store document")

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")
    return updated


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
)
async def update_document(
    document_id: UUID,
    payload: DocumentRelinkUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_manager_or_above),
    document_service: DocumentService = Depends(get_document_service),
):
    try:

        updated = await document_service.update_document(db, document_id, payload, current_user=current_user)
        return updated
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DocumentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    storage_client=Depends(get_storage_client),
    current_user: object = Depends(require_manager_or_above),
    document_service: DocumentService = Depends(get_document_service),
):
    try:
        deleted = await document_service.delete_document(
            db,
            document_id,
            storage_client=storage_client,
            current_user=current_user,
        )
        return deleted
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DocumentForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except DocumentDeletionError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
