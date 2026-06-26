from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.contract import ContractCreate, ContractUpdate, ContractResponse
from app.services.contract_service import ContractService
from app.core.dependencies import get_contract_service, require_manager_or_above, get_property_service
from app.models.user import UserRole
from app.services.property_service import PropertyService
from app.services.exceptions import ContractActiveError

router = APIRouter(prefix="/contracts", tags=["Contracts"])


@router.get(
    "/",
    response_model=list[ContractResponse],
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
    contract = await contract_service.get_contract(db, contract_id)
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Contract {contract_id} not found")
    return contract


@router.post(
    "/",
    response_model=ContractResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract(
    payload: ContractCreate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_manager_or_above),
    property_service: PropertyService = Depends(get_property_service),
    contract_service: ContractService = Depends(get_contract_service),
):
    try:
        # Resource-level auth: managers may only create contracts for properties
        # they are assigned to. Admins can create for any property.
        prop = await property_service.get_property(db, payload.property_id)
        if (
            prop is not None
            and getattr(current_user, "role", None) == UserRole.MANAGER
            and prop.manager_id != current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Manager not authorized for this property"
            )

        return await contract_service.create_contract(db, payload)
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
    property_service: PropertyService = Depends(get_property_service),
    contract_service: ContractService = Depends(get_contract_service),
):
    # Fetch contract to perform resource-level authorization check first
    contract = await contract_service.get_contract(db, contract_id)
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Contract {contract_id} not found")

    if getattr(current_user, "role", None) == UserRole.MANAGER:
        prop = await property_service.get_property(db, contract.property_id)
        if not prop or prop.manager_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Manager not authorized for this property"
            )

    updated = await contract_service.update_contract(db, contract_id, payload)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Contract {contract_id} not found")
    return updated


@router.delete(
    "/{contract_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contract(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_manager_or_above),
    property_service: PropertyService = Depends(get_property_service),
    contract_service: ContractService = Depends(get_contract_service),
):
    contract = await contract_service.get_contract(db, contract_id)
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Contract {contract_id} not found")

    if getattr(current_user, "role", None) == UserRole.MANAGER:
        prop = await property_service.get_property(db, contract.property_id)
        if not prop or prop.manager_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Manager not authorized for this property"
            )

    deleted = await contract_service.delete_contract(db, contract_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Contract {contract_id} not found")
