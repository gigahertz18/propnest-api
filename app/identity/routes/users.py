from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.identity.schemas.user import UserCreate, UserUpdate, UserResponse
from app.core.dependencies import require_admin, get_current_user, get_user_service
from app.identity.models.user import User
from app.identity.services.user_service import UserService
from app.core.services.exceptions import (
    UserNotFoundError,
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
    ManagerAssignedToPropertyError,
    CurrentPasswordRequiredError,
    InvalidCredentialsError,
)
from uuid import UUID

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=list[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_admin),
):
    """Get all users. Admin only."""
    return await user_service.list_users(db, current_user, skip=skip, limit=limit)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
):
    """
    Get a user by ID.
    Admins can view any user. Regular users can only view themselves.
    """

    try:
        return await user_service.get_user(db, user_id, current_user=current_user)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_admin),
):
    """Create a new user. Admin only."""
    try:
        return await user_service.create_user(db, payload, current_user)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )
    except UsernameAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this username already exists",
        )


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
):
    """
    Update a user.
    Admins can update any user. Regular users can only update themselves.
    """
    try:
        return await user_service.update_user(db, user_id, payload, current_user)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )
    except UsernameAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this username already exists",
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    except CurrentPasswordRequiredError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except InvalidCredentialsError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    user_service: UserService = Depends(get_user_service),
) -> None:
    """Delete a user. Admin only."""

    try:
        await user_service.delete_user(db, user_id, current_user)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    except ManagerAssignedToPropertyError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
