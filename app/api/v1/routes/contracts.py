from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.contract import ContractCreate, ContractUpdate, ContractResponse
from app.services.contract_service import ContractService
from app.core.dependencies import get_contract_service
from app.services.exceptions import ContractActiveError

router = APIRouter(prefix="/contracts", tags=["Contracts"])


@router.get("/", response_model=list[ContractResponse])
def list_contracts(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    contract_service: ContractService = Depends(get_contract_service),
):
    return contract_service.list_contracts(db, skip=skip, limit=limit)


@router.get("/{contract_id}", response_model=ContractResponse)
def get_contract(
    contract_id: UUID,
    db: Session = Depends(get_db),
    contract_service: ContractService = Depends(get_contract_service),
):
    contract = contract_service.get_contract(db, contract_id)
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Contract {contract_id} not found")
    return contract


@router.post("/", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
def create_contract(
    payload: ContractCreate,
    db: Session = Depends(get_db),
    contract_service: ContractService = Depends(get_contract_service),
):
    try:
        return contract_service.create_contract(db, payload)
    except ContractActiveError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Property already has an active contract")


@router.patch("/{contract_id}", response_model=ContractResponse)
def update_contract(
    contract_id: UUID,
    payload: ContractUpdate,
    db: Session = Depends(get_db),
    contract_service: ContractService = Depends(get_contract_service),
):
    contract = contract_service.update_contract(db, contract_id, payload)
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Contract {contract_id} not found")
    return contract


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(
    contract_id: UUID,
    db: Session = Depends(get_db),
    contract_service: ContractService = Depends(get_contract_service),
):
    contract = contract_service.delete_contract(db, contract_id)
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Contract {contract_id} not found")
