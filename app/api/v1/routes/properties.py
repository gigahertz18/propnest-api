from uuid import UUID

from app.core.dependencies import require_admin
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyResponse
from app.repositories import property_repo

router = APIRouter(prefix="/properties", tags=["Properties"])


@router.get("/", response_model=list[PropertyResponse])
def list_properties(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Get all properties."""
    return property_repo.get_all(db, skip=skip, limit=limit)


@router.get("/{property_id}", response_model=PropertyResponse)
def get_property(
    property_id: UUID,
    db: Session = Depends(get_db),
):
    """Get a single property by ID."""
    property = property_repo.get_by_id(db, property_id)
    if not property:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Property {property_id} not found",
        )
    return property


@router.post(
    "/",
    response_model=PropertyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_property(
    payload: PropertyCreate,
    db: Session = Depends(get_db),
):
    """Create a new property."""
    return property_repo.create(db, payload)


@router.patch("/{property_id}", response_model=PropertyResponse, dependencies=[Depends(require_admin)])
def update_property(
    property_id: UUID,
    payload: PropertyUpdate,
    db: Session = Depends(get_db),
):
    """Partially update a property — only send fields you want to change."""
    property = property_repo.update(db, property_id, payload)
    if not property:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Property {property_id} not found",
        )
    return property


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_property(
    property_id: UUID,
    db: Session = Depends(get_db),
):
    """Delete a property."""
    property = property_repo.delete(db, property_id)
    if not property:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Property {property_id} not found",
        )
