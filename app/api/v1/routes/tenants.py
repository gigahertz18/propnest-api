from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.schemas.tenant import TenantCreate, TenantUpdate, TenantResponse, TenantLinkUser
from app.services.tenant_service import TenantService
from app.core.dependencies import get_tenant_service, require_manager_or_above, get_current_user
from app.services.exceptions import (
    RelatedResourceNotFoundError,
    UserNotFoundError,
    TenantAlreadyLinkedError,
    TenantForbiddenError,
)

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get("/", response_model=list[TenantResponse], dependencies=[Depends(get_current_user)])
async def list_tenants(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(require_manager_or_above),
):
    return await tenant_service.list_tenants(db, skip=skip, limit=limit, current_user=current_user)


@router.get("/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(get_current_user)])
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(require_manager_or_above),
):
    try:
        return await tenant_service.get_tenant(db, tenant_id, current_user=current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TenantForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_manager_or_above)],
)
async def create_tenant(
    payload: TenantCreate,
    db: AsyncSession = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    return await tenant_service.create_tenant(db, payload)


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponse,
)
async def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(require_manager_or_above),
):
    try:
        return await tenant_service.update_tenant(db, tenant_id, payload, current_user=current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TenantForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(require_manager_or_above),
):
    try:
        return await tenant_service.delete_tenant(db, tenant_id, current_user=current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TenantForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put(
    "/{tenant_id}/link-user",
    response_model=TenantResponse,
)
async def link_tenant_user(
    tenant_id: UUID,
    payload: TenantLinkUser,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    Link a tenant to a portal-access User account, granting them the
    ability to log in and view their own rental data. Manager/admin only —
    a tenant cannot link themselves, since that would let anyone claim an
    existing tenant record by guessing its ID.
    """
    try:
        return await tenant_service.link_user(db, tenant_id, payload.user_id, current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TenantAlreadyLinkedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except TenantForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete(
    "/{tenant_id}/link-user",
    response_model=TenantResponse,
)
async def unlink_tenant_user(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """Remove portal-access linkage. The tenant record and its contracts/
    documents are untouched — only the user_id association is cleared."""
    try:
        return await tenant_service.unlink_user(db, tenant_id, current_user)
    except RelatedResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TenantForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
