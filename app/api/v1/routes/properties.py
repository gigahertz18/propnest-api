from uuid import UUID

from app.core.dependencies import require_admin, get_property_service, get_current_user
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyResponse
from app.services.property_service import PropertyService

router = APIRouter(prefix="/properties", tags=["Properties"])


@router.get(
    "/",
    response_model=list[PropertyResponse],
    dependencies=[Depends(get_current_user)],
)
def list_properties(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Get all properties."""
    return property_service.list_properties(db, skip=skip, limit=limit)


@router.get(
    "/{property_id}",
    response_model=PropertyResponse,
    dependencies=[Depends(get_current_user)],
)
def get_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Get a single property by ID."""
    prop = property_service.get_property(db, property_id)
    if not prop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Property {property_id} not found",
        )
    return prop


@router.post(
    "/",
    response_model=PropertyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_property(
    payload: PropertyCreate,
    db: Session = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Create a new property."""
    return property_service.create_property(db, payload)


@router.patch("/{property_id}", response_model=PropertyResponse, dependencies=[Depends(require_admin)])
def update_property(
    property_id: UUID,
    payload: PropertyUpdate,
    db: Session = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Partially update a property — only send fields you want to change."""
    prop = property_service.update_property(db, property_id, payload)
    if not prop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Property {property_id} not found",
        )
    return prop


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    property_service: PropertyService = Depends(get_property_service),
):
    """Delete a property."""
    prop = property_service.delete_property(db, property_id)
    if not prop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Property {property_id} not found",
        )
