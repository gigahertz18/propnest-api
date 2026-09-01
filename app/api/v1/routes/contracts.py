from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID


from app.core.dependencies import get_contract_service, require_manager_or_above
from app.db.session import get_db
from app.models.user import User
from app.core.schemas.base import PaginatedResponse
from app.schemas.contract import ContractCreate, ContractUpdate, ContractResponse
from app.services.contract_service import ContractService
from app.core.services.exceptions import (
    ContractActiveError,
    ContractInUseError,
)

router = APIRouter(prefix="/contracts", tags=["Contracts"])


@router.get(
    "/",
    response_model=PaginatedResponse[ContractResponse],
)
async def list_contracts(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    contract_service: ContractService = Depends(get_contract_service),
    current_user: User = Depends(require_manager_or_above),
):
    """List contracts. Managers only see contracts for properties they're assigned to; admins see all."""
    return await contract_service.list_contracts(db, current_user, skip=skip, limit=limit)


@router.get(
    "/{contract_id}",
    response_model=ContractResponse,
)
async def get_contract(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    contract_service: ContractService = Depends(get_contract_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Get a single contract by ID."""
    return await contract_service.get_contract(db, contract_id, current_user)


@router.post(
    "/",
    response_model=ContractResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract(
    payload: ContractCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    contract_service: ContractService = Depends(get_contract_service),
):
    """
    Create a new rental contract for a property/tenant pair.

    Managers may only create contracts for properties they're assigned to;
    admins can create for any property. Fails with 409 if the property
    already has an active contract.
    """
    try:
        # Resource-level auth: managers may only create contracts for properties
        # they are assigned to. Admins can create for any property.
        return await contract_service.create_contract(db, payload, current_user)
    except ContractActiveError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Property already has an active contract")


@router.patch(
    "/{contract_id}",
    response_model=ContractResponse,
)
async def update_contract(
    contract_id: UUID,
    payload: ContractUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_manager_or_above),
    contract_service: ContractService = Depends(get_contract_service),
):
    """Update a contract. Fails with 409 if the property already has a different active contract."""
    try:
        return await contract_service.update_contract(db, contract_id, payload, current_user)
    except ContractActiveError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Property already has an active contract")


@router.delete(
    "/{contract_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contract(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_manager_or_above),
    contract_service: ContractService = Depends(get_contract_service),
) -> None:
    """Delete a contract. Fails with 409 if the contract is still referenced by a lease/collection."""
    try:
        await contract_service.delete_contract(db, contract_id, current_user)
    except ContractInUseError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
