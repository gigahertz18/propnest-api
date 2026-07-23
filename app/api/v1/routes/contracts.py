from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID


from app.core.dependencies import get_contract_service, require_manager_or_above
from app.db.session import get_db
from app.models.user import User
from app.schemas.base import PaginatedResponse
from app.schemas.contract import ContractCreate, ContractUpdate, ContractResponse
from app.services.contract_service import ContractService
from app.services.exceptions import (
    ContractActiveError,
    RelatedResourceNotFoundError,
    ContractForbiddenError,
    ContractInUseError,
)

router = APIRouter(prefix="/contracts", tags=["Contracts"])


@router.get(
    "/",
    response_model=PaginatedResponse[ContractResponse],
    dependencies=[Depends(require_manager_or_above)],
)
async def list_contracts(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    contract_service: ContractService = Depends(get_contract_service),
):
    return await contract_service.list_contracts(db, skip=skip, limit=limit)


@router.get(
    "/{contract_id}",
    response_model=ContractResponse,
    dependencies=[Depends(require_manager_or_above)],
)
async def get_contract(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    contract_service: ContractService = Depends(get_contract_service),
):
    try:
        return await contract_service.get_contract(db, contract_id)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


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
    try:
        # Resource-level auth: managers may only create contracts for properties
        # they are assigned to. Admins can create for any property.
        return await contract_service.create_contract(db, payload, current_user)
    except ContractActiveError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Property already has an active contract")
    except ContractForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


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
    try:
        return await contract_service.update_contract(db, contract_id, payload, current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ContractForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
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
):
    try:
        return await contract_service.delete_contract(db, contract_id, current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ContractForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ContractInUseError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
