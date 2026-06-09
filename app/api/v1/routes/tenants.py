from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.tenants import TenantCreate, TenantUpdate, TenantResponse
from app.services.tenant_service import TenantService
from app.core.dependencies import get_tenant_service, require_manager_or_above, get_current_user
from app.models.user import User

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get("/", response_model=list[TenantResponse], dependencies=[Depends(get_current_user)])
def list_tenants(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    return tenant_service.list_tenants(db, skip=skip, limit=limit)


@router.get("/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(get_current_user)])
def get_tenant(
    tenant_id: UUID,
    db: Session = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    tenant = tenant_service.get_tenant(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    return tenant


@router.post(
    "/",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_user)],
)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    return tenant_service.create_tenant(db, payload)


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponse,
    dependencies=[Depends(get_current_user)],
)
def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdate,
    db: Session = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    tenant = tenant_service.update_tenant(db, tenant_id, payload)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    return tenant


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_manager_or_above)],
)
def delete_tenant(
    tenant_id: UUID,
    db: Session = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    tenant = tenant_service.delete_tenant(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
