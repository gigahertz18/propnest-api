import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.schemas.user import UserLogin, TokenResponse, UserResponse
from app.services.auth_service import AuthService
from app.services.exceptions import AccountLockedError, InvalidCredentialsError
from app.core.dependencies import get_current_user, get_auth_service
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.LOGIN_RATE_LIMIT_PER_IP)
async def login(
    request: Request,
    payload: UserLogin,
    db: AsyncSession = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Login with username or email + password.
    Returns a JWT access token on success.
    
    Two independent layers of throttling sit above credential checking:
    - Per-IP request rate limiting (this decorator, Redis-backed)
    - Per-identifier progressive lockout after repeated failures, enforced inside AuthService.login
    """
    client_ip = request.client.host if request.client else None
    try:
        return await auth_service.login(db, payload.identifier, payload.password, client_ip=client_ip)
    except AccountLockedError as e:
        logger.warning(f"Login blocked by lockout (ip={client_ip})")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(e.retry_after_seconds)}
        )
    except InvalidCredentialsError:
        logger.warning("Failed login attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Returns the currently authenticated user's profile."""
    return auth_service.get_profile(current_user)
