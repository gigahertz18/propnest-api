from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_collection_service, require_manager_or_above, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.base import PaginatedResponse
from app.schemas.collection import CollectionCreate, CollectionUpdate, CollectionResponse
from app.services.collection_service import CollectionService
from app.services.exceptions import CollectionValidationError

router = APIRouter(prefix="/collections", tags=["Collections"])


@router.get("/", response_model=PaginatedResponse[CollectionResponse], dependencies=[Depends(get_current_user)])
async def list_collections(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    collection_service: CollectionService = Depends(get_collection_service),
    current_user: User = Depends(require_manager_or_above),
):
    """List collection records."""
    return await collection_service.list_collections(db, current_user=current_user, skip=skip, limit=limit)


@router.get("/{collection_id}", response_model=CollectionResponse, dependencies=[Depends(get_current_user)])
async def get_collection(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    collection_service: CollectionService = Depends(get_collection_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Get a single collection record by ID."""
    return await collection_service.get_collection(db, collection_id, current_user=current_user)


@router.post(
    "/",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    payload: CollectionCreate,
    db: AsyncSession = Depends(get_db),
    collection_service: CollectionService = Depends(get_collection_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Create a new collection record, optionally linked to a contract."""
    try:
        return await collection_service.create_collection(db, payload, current_user=current_user)
    except CollectionValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch(
    "/{collection_id}",
    response_model=CollectionResponse,
)
async def update_collection(
    collection_id: UUID,
    payload: CollectionUpdate,
    db: AsyncSession = Depends(get_db),
    collection_service: CollectionService = Depends(get_collection_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Update a collection record, including reassigning or clearing its linked contract."""
    try:
        return await collection_service.update_collection(db, collection_id, payload, current_user=current_user)
    except CollectionValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/{collection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_collection(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    collection_service: CollectionService = Depends(get_collection_service),
    current_user: User = Depends(require_manager_or_above),
) -> None:
    """Delete a collection record."""
    await collection_service.delete_collection(db, collection_id, current_user=current_user)
