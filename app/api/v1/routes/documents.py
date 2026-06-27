from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.document import DocumentCreate, DocumentUpdate, DocumentResponse
from app.services.document_service import DocumentService
from app.core.dependencies import (
    get_document_service,
    require_manager_or_above,
    get_storage_client,
    get_property_service,
    get_contract_service,
    get_current_user,
)
from app.models.user import UserRole
from app.services.property_service import PropertyService
from app.services.contract_service import ContractService
from app.services.exceptions import DocumentUploadError

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get(
    "/",
    response_model=list[DocumentResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_documents(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
):
    return await document_service.list_documents(db, skip=skip, limit=limit)


@router.get("/{document_id}", response_model=DocumentResponse, dependencies=[Depends(get_current_user)])
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    document_service: DocumentService = Depends(get_document_service),
):
    document = await document_service.get_document(db, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")
    return document


@router.post(
    "/",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    payload: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_manager_or_above),
    property_service: PropertyService = Depends(get_property_service),
    document_service: DocumentService = Depends(get_document_service),
):
    try:
        # Resource-level auth: managers may only create documents for properties
        # they are assigned to. Admins can create for any property.
        prop = await property_service.get_property(db, payload.property_id)
        if not prop:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Property {payload.property_id} not found."
            )
        if (
            prop.manager_id != current_user.id
            and getattr(current_user, "role", None) == UserRole.MANAGER
            
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Manager not authorized for this property"
            )

        # Routes don't provide a storage client — services can be tested separately
        return await document_service.create_document(db, payload)
    except DocumentUploadError:
        # External storage failures are transient — surface as 503
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to store document")


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
    property_service: PropertyService = Depends(get_property_service),
    document_service: DocumentService = Depends(get_document_service),
):
    """Accept multipart/form uploads and stream directly to storage.

    This endpoint keeps metadata in sync with the storage object.
    """
    if property_id is not None:
        prop = await property_service.get_property(db, property_id)
        if not prop:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Property {property_id} not found."
            )
            
        if ( 
            prop.manager_id != current_user.id
            and getattr(current_user, "role", None) == UserRole.MANAGER
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Manager not authorized for this property"
            )

    # Resolve the object URL before touching the DB —
    # if the upload fails, no orphaned DB record is created.
    object_url = document_service._build_object_url(file.filename)
    payload = DocumentCreate(
        file_name=file.filename,
        file_type=file_type,
        file_url=object_url,
        contract_id=contract_id,
        property_id=property_id,
        tenant_id=tenant_id,
    )
    
    try:
        return await document_service.create_document(db, payload, storage_client=storage_client, file_obj=file)
    except DocumentUploadError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to store document")


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
)
async def update_document(
    document_id: UUID,
    payload: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_manager_or_above),
    property_service: PropertyService = Depends(get_property_service),
    contract_service: ContractService = Depends(get_contract_service),
    document_service: DocumentService = Depends(get_document_service),
):
    # Fetch document first to perform resource-level authorization
    document = await document_service.get_document(db, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")

    if getattr(current_user, "role", None) == UserRole.MANAGER:
        prop = None
        if getattr(document, "property_id", None):
            prop = await property_service.get_property(db, document.property_id)
        elif getattr(document, "contract_id", None):
            contract = await contract_service.get_contract(db, document.contract_id)
            if contract:
                prop = await property_service.get_property(db, contract.property_id)

        if not prop or prop.manager_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Manager not authorized for this property"
            )

    updated = await document_service.update_document(db, document_id, payload)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")
    return updated


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_manager_or_above),
    property_service: PropertyService = Depends(get_property_service),
    contract_service: ContractService = Depends(get_contract_service),
    document_service: DocumentService = Depends(get_document_service),
):
    document = await document_service.get_document(db, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")

    if getattr(current_user, "role", None) == UserRole.MANAGER:
        prop = None
        if getattr(document, "property_id", None):
            prop = await property_service.get_property(db, document.property_id)
        elif getattr(document, "contract_id", None):
            contract = await contract_service.get_contract(db, document.contract_id)
            if contract:
                prop = await property_service.get_property(db, contract.property_id)

        if not prop or prop.manager_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Manager not authorized for this property"
            )

    deleted = await document_service.delete_document(db, document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")
