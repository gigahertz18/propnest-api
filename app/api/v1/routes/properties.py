from uuid import UUID

from app.core.dependencies import require_admin, get_property_service, get_current_user
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyResponse
from app.services.property_service import PropertyService
from app.services.exceptions import RelatedResourceNotFoundError, PropertyAlreadyExistsError

router = APIRouter(prefix="/properties", tags=["Properties"])


@router.get(
    "/",
    response_model=list[PropertyResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_properties(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Get all properties."""
    return await property_service.list_properties(db, skip=skip, limit=limit)


@router.get(
    "/{property_id}",
    response_model=PropertyResponse,
    dependencies=[Depends(get_current_user)],
)
async def get_property(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Get a single property by ID."""
    try:
        return await property_service.get_property(db, property_id)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/",
    response_model=PropertyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_property(
    payload: PropertyCreate,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Create a new property."""
    try:
        return await property_service.create_property(db, payload)
    except PropertyAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.patch("/{property_id}", response_model=PropertyResponse, dependencies=[Depends(require_admin)])
async def update_property(
    property_id: UUID,
    payload: PropertyUpdate,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Partially update a property — only send fields you want to change."""
    try:
        return await property_service.update_property(db, property_id, payload)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PropertyAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_property(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Delete a property."""
    try:
        return await property_service.delete_property(db, property_id)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
