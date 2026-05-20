import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.user import UserLogin, TokenResponse, UserResponse
from app.services.auth_service import AuthService
from app.services.exceptions import InvalidCredentialsError
from app.core.dependencies import get_current_user, get_auth_service
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: UserLogin,
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Login with username or email + password.
    Returns a JWT access token on success.
    """
    try:
        return auth_service.login(db, payload.identifier, payload.password)
    except InvalidCredentialsError:
        logger.warning("Failed login attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/me", response_model=UserResponse)
def me(
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Returns the currently authenticated user's profile."""
    return auth_service.get_profile(current_user)
