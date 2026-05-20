from sqlalchemy.orm import Session

from app.core.security import verify_password, create_access_token
from app.repositories.user import UserRepository
from app.schemas.user import TokenResponse, UserResponse
from app.models.user import User
from app.services.exceptions import InvalidCredentialsError


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

        if not user:
            # run a dummy verify to mitigate timing attacks for non-existent users
            verify_password(password, None)
            raise InvalidCredentialsError("The identifier or password you entered is incorrect.")

        # Verify password (will also use dummy_verify internally on error)
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("The identifier or password you entered is incorrect.")

        # Do not return a distinct error for inactive accounts (avoid confirming password correctness).
        if not user.is_active:
            raise InvalidCredentialsError("The identifier or password you entered is incorrect.")

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


# Note: no module-level AuthService singleton here. Use a FastAPI dependency
# (`get_auth_service`) to construct/override in tests.
