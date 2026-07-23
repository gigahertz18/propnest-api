import logging

from minio import Minio
from urllib.parse import urlparse
from uuid import UUID


from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db

from app.models.user import User, UserRole

from app.repositories.contract import contract_repo
from app.repositories.document import document_repo
from app.repositories.property import property_repo
from app.repositories.payment import payment_repo
from app.repositories.tenant import tenant_repo
from app.repositories.user import user_repo

from app.services.auth_service import AuthService
from app.services.contract_service import ContractService
from app.services.document_service import DocumentService
from app.services.payment_service import PaymentService
from app.services.property_service import PropertyService
from app.services.tenant_service import TenantService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency — decodes the JWT and returns the current user.
    Use this on any route that requires authentication.

    Usage:
        def my_route(current_user: User = Depends(get_current_user)):
    """
    token = credentials.credentials
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str | None = payload.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await user_repo.get_by_id(db, user_uuid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    return user


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    FastAPI dependency — same as get_current_user but also checks for admin role.
    Use this on any route that requires admin access.

    Usage:
        def my_route(current_user: User = Depends(require_admin)):
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def require_manager_or_above(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Requires ADMIN or MANAGER role.
    Use on routes that managers and admins can access but regular users cannot.

    Usage:
        def my_route(current_user: User = Depends(require_manager_or_above)):
    """
    if current_user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager access required",
        )
    return current_user


def get_auth_service() -> AuthService:
    """
    FastAPI dependency to construct `AuthService`. Kept simple so tests can
    override this dependency if needed.
    """
    return AuthService(user_repo=user_repo)


def get_user_service() -> UserService:
    """Construct a `UserService` for FastAPI dependency injection."""
    return UserService(user_repo=user_repo)


def get_property_service() -> PropertyService:
    return PropertyService(
        property_repo=property_repo,
        user_repo=user_repo,
    )


def get_contract_service() -> ContractService:
    return ContractService(
        contract_repo=contract_repo, 
        property_repo=property_repo, 
        tenant_repo=tenant_repo,
    )


def get_tenant_service() -> TenantService:
    return TenantService(tenant_repo=tenant_repo, user_repo=user_repo)


def get_document_service() -> DocumentService:
    return DocumentService(
        document_repo=document_repo,
        property_repo=property_repo,
        contract_repo=contract_repo,
        tenant_repo=tenant_repo,
    )


def get_payment_service() -> PaymentService:
    return PaymentService(
        payment_repo=payment_repo,
        contract_repo=contract_repo,
        property_repo=property_repo,
    )


def get_storage_client() -> Minio:
    """Constructs a MinIO client using settings.

    Returns a fresh client instance. Tests can override this dependency.
    """
    parsed = urlparse(settings.MINIO_ENDPOINT)
    endpoint = parsed.netloc or parsed.path
    secure = parsed.scheme == "https"
    return Minio(
        endpoint,
        access_key=settings.MINIO_ROOT_USER,
        secret_key=settings.MINIO_ROOT_PASSWORD,
        secure=secure,
    )
