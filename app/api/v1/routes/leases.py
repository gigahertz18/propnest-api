from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_lease_service, require_manager_or_above
from app.db.session import get_db
from app.identity.models.user import User
from app.core.schemas.base import PaginatedResponse
from app.schemas.lease import LeaseCreate, LeaseUpdate, LeaseResponse
from app.services.lease_service import LeaseService
from app.core.services.exceptions import LeaseAlreadyExistsError, LeaseRentalTypeError

router = APIRouter(prefix="/leases", tags=["Leases"])


@router.get(
    "/",
    response_model=PaginatedResponse[LeaseResponse],
)
async def list_leases(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    lease_service: LeaseService = Depends(get_lease_service),
    current_user: User = Depends(require_manager_or_above),
):
    """List leases."""
    return await lease_service.list_leases(db, current_user, skip=skip, limit=limit)


@router.get(
    "/{lease_id}",
    response_model=LeaseResponse,
)
async def get_lease(
    lease_id: UUID,
    db: AsyncSession = Depends(get_db),
    lease_service: LeaseService = Depends(get_lease_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Get a single lease by ID."""
    return await lease_service.get_lease(db, lease_id, current_user)


@router.post(
    "/",
    response_model=LeaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_lease(
    payload: LeaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    lease_service: LeaseService = Depends(get_lease_service),
):
    """
    Create a new lease for a contract.

    Fails with 400 if the rental type doesn't match the contract's terms,
    and with 409 if the contract already has a lease.
    """
    try:
        return await lease_service.create_lease(db, payload, current_user)
    except LeaseRentalTypeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except LeaseAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.patch(
    "/{lease_id}",
    response_model=LeaseResponse,
)
async def update_lease(
    lease_id: UUID,
    payload: LeaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    lease_service: LeaseService = Depends(get_lease_service),
):
    """Update a lease."""
    return await lease_service.update_lease(db, lease_id, payload, current_user)


@router.delete(
    "/{lease_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_lease(
    lease_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    lease_service: LeaseService = Depends(get_lease_service),
) -> None:
    """Delete a lease."""
    await lease_service.delete_lease(db, lease_id, current_user)
