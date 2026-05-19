from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import decode_access_token
from app.repositories.user import user_repo
from app.models.user import User, UserRole
from app.services.auth_service import AuthService

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
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

    user = user_repo.get_by_id(db, user_uuid)
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
