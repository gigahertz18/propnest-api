import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.user import UserLogin, TokenResponse, UserResponse
from app.services import auth_service
from app.services.exceptions import InvalidCredentialsError, AccountInactiveError
from app.core.dependencies import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login", response_model=TokenResponse)
def login(
    payload: UserLogin,
    db: Session = Depends(get_db),
):
    """
    Login with username or email + password.
    Returns a JWT access token on success.
    """
    try:
        return auth_service.login(db, payload.identifier, payload.password)
    except InvalidCredentialsError:
        logger.error("Failed login attempt for identifier: %s", payload.identifier)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except AccountInactiveError:
        logger.error("Login attempt for inactive account: %s", payload.identifier)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    """Returns the currently authenticated user's profile."""
    return auth_service.get_profile(current_user)
