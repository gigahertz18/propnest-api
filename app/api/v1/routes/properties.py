from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import require_admin, get_property_service, require_manager_or_above
from app.db.session import get_db
from app.models.user import User
from app.schemas.base import PaginatedResponse
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyResponse, PropertyAssignManager
from app.services.property_service import PropertyService
from app.services.exceptions import (
    RelatedResourceNotFoundError,
    PropertyAlreadyExistsError,
    PropertyForbiddenError,
    UserNotFoundError,
    PropertyManagerAssignmentError,
)

router = APIRouter(prefix="/properties", tags=["Properties"])


@router.get(
    "/",
    response_model=PaginatedResponse[PropertyResponse],
)
async def list_properties(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Get all properties."""
    return await property_service.list_properties(db, current_user=current_user, skip=skip, limit=limit)


@router.get(
    "/{property_id}",
    response_model=PropertyResponse,
)
async def get_property(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Get a single property by ID."""
    try:
        return await property_service.get_property(db, property_id, current_user=current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PropertyForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


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


@router.patch("/{property_id}", response_model=PropertyResponse)
async def update_property(
    property_id: UUID,
    payload: PropertyUpdate,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
    current_user: User = Depends(require_admin),
):
    """Partially update a property — only send fields you want to change."""
    try:
        return await property_service.update_property(db, property_id, payload, current_user=current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PropertyAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
    current_user: User = Depends(require_admin),
):
    """Delete a property."""
    try:
        await property_service.delete_property(db, property_id, current_user=current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch(
    "/{property_id}/assign-manager",
    response_model=PropertyResponse,
)
async def assign_manager(
    property_id: UUID,
    payload: PropertyAssignManager,
    db: AsyncSession = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
    current_user: User = Depends(require_admin),
):
    """
    Assign a manager to a property. Admin only.

    This is the only code path that populates `Property.manager_id`
    through the API — every manager-scoped authorization check across
    Property, Contract, Document, and Payment depends on it being set this
    way. Reassigning simply overwrites the previous manager; a property is
    expected to be reassigned when a new contract goes active rather than
    explicitly unassigned in between.
    """

    try:
        return await property_service.assign_manager(db, property_id, payload.manager_id, current_user)

    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PropertyManagerAssignmentError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
