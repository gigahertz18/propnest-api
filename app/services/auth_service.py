import logging

from sqlalchemy.orm import Session

from app.core.security import verify_password, create_access_token
from app.repositories.user import UserRepository
from app.schemas.user import TokenResponse, UserResponse
from app.models.user import User
from app.services.exceptions import (
    InvalidCredentialsError,
    AccountInactiveError,
)


logger = logging.getLogger(__name__)

class AuthService:
    """
    Handles all authentication business logic.

    Responsibilities:
    - Validating credentials
    - Checking account state
    - Generating JWT tokens

    Raises domain exceptions (not HTTP exceptions) —
    the route layer is responsible for converting these to HTTP responses.
    """

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    def login(self, db: Session, identifier: str, password: str) -> TokenResponse:
        """
        Authenticate a user by username or email + password.

        Raises:
            InvalidCredentialsError: if identifier not found or password is wrong.
            AccountInactiveError: if the user exists but is deactivated.

        Returns:
            TokenResponse with a signed JWT access token.
        """
        user = self.user_repo.get_by_identifier(db, identifier)

        # Check credentials — generic check so we don't reveal if user exists
        if not user or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("The identifier or password you entered is incorrect.")

        if not user.is_active:
            raise AccountInactiveError("This account has been deactivated. Contact an administrator.")

        token = self._issue_token(user)
        return TokenResponse(access_token=token)

    def get_profile(self, current_user: User) -> UserResponse:
        """
        Return the authenticated user's profile.

        No DB call needed — current_user is already loaded by the
        get_current_user dependency.

        Returns:
            UserResponse of the currently authenticated user.
        """
        return UserResponse.model_validate(current_user)

    # ─── Private ──────────────────────────────────────────
    def _issue_token(self, user: User) -> str:
        """Build and sign the JWT payload for the given user."""
        return create_access_token(
            data={
                "sub": str(user.id),
                "role": user.role.value,
                "username": user.username,
            }
        )


# ─── Singleton ────────────────────────────────────────────
# Import user_repo here to avoid circular imports at module level
from app.repositories.user import user_repo  # noqa: E402

auth_service = AuthService(user_repo=user_repo)
