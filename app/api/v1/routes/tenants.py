from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.dependencies import get_tenant_service, require_manager_or_above, get_current_user
from app.db.session import get_db
from app.identity.models.user import User
from app.core.schemas.base import PaginatedResponse
from app.schemas.tenant import TenantCreate, TenantUpdate, TenantResponse, TenantLinkUser
from app.core.services.exceptions import (
    UserNotFoundError,
    TenantAlreadyLinkedError,
    TenantAlreadyExistsError,
    TenantInUseError,
)
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get("/", response_model=PaginatedResponse[TenantResponse], dependencies=[Depends(get_current_user)])
async def list_tenants(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(require_manager_or_above),
):
    """List tenants."""
    return await tenant_service.list_tenants(db, skip=skip, limit=limit, current_user=current_user)


@router.get("/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(get_current_user)])
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Get a single tenant by ID."""
    return await tenant_service.get_tenant(db, tenant_id, current_user=current_user)


@router.post(
    "/",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    payload: TenantCreate,
    db: AsyncSession = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(require_manager_or_above),
):
    """Create a new tenant record. Fails with 409 if a matching tenant already exists."""
    try:
        return await tenant_service.create_tenant(db, payload, current_user=current_user)
    except TenantAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


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
    """Update a tenant record. Fails with 409 if the update would collide with an existing tenant."""
    try:
        return await tenant_service.update_tenant(db, tenant_id, payload, current_user=current_user)
    except TenantAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(require_manager_or_above),
) -> None:
    """Delete a tenant. Fails with 409 if the tenant is still referenced by a contract."""
    try:
        await tenant_service.delete_tenant(db, tenant_id, current_user=current_user)
    except TenantInUseError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


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
    except UserNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TenantAlreadyLinkedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


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
    return await tenant_service.unlink_user(db, tenant_id, current_user)
