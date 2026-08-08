import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password, create_access_token
from app.repositories.user import UserRepository
from app.repositories.login_attempt import LoginAttemptRepository
from app.schemas.user import TokenResponse, UserResponse
from app.models.user import User
from app.services.exceptions import AccountLockedError, InvalidCredentialsError

logger = logging.getLogger(__name__)

class AuthService:
    """
    Handles all authentication business logic.

    Responsibilities:
    - Validating credentials
    - Checking account state
    - Throttling repeated failures per identifier (progressive lockout)
    - Generating JWT tokens

    Raises domain exceptions (not HTTP exceptions) —
    the route layer is responsible for converting these to HTTP responses.
    """

    def __init__(self, user_repo: UserRepository, login_attempt_repo: LoginAttemptRepository) -> None:
        self.user_repo = user_repo
        self.login_attempt_repo = login_attempt_repo

    async def login(self, db: AsyncSession, identifier: str, password: str, client_ip: str | None = None,) -> TokenResponse:
        """
        Authenticate a user by username or email + password.
        
        `client_ip` is log-only context (who's attempting) - it does not  affect 
        lockout keying, which is per-identifier regardless of source IP.
        Per-IP request volume is throttled seperately, at the route layer, via app.core_rate_limit.limiter.

        Raises:
            InvalidCredentialsError: if identifier not found or password is wrong.
            AccountInactiveError: if the user exists but is deactivated.

        Returns:
            TokenResponse with a signed JWT access token.
        """
        lock_status = await self.login_attempt_repo.get_lock_status(identifier)
        if lock_status.locked:
            logger.warning(
                "Login blocked — identifier is locked out (identifier=%s, ip=%s, retry_after=%ss)",
                identifier,
                client_ip,
                lock_status.retry_after_seconds,
            )
            raise AccountLockedError(lock_status.retry_after_seconds)

        user = await self.user_repo.get_by_identifier(db, identifier)

        if not user:
            # run a dummy verify to mitigate timing attacks for non-existent users
            verify_password(password, None)
            await self._record_failure(identifier, client_ip)
            raise InvalidCredentialsError("The identifier or password you entered is incorrect.")

        # Verify password (will also use dummy_verify internally on error)
        if not verify_password(password, user.password_hash):
            await self._record_failure(identifier, client_ip)
            raise InvalidCredentialsError("The identifier or password you entered is incorrect.")

        # Do not return a distinct error for inactive accounts (avoid confirming password correctness).
        if not user.is_active:
            await self._record_failure(identifier, client_ip)
            raise InvalidCredentialsError("The identifier or password you entered is incorrect.")

        await self.login_attempt_repo.record_success(identifier)
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
    async def _record_failure(self, identifier: str, client_ip: str | None) -> None:
        lock_status = await self.login_attempt_repo.record_failure(identifier)
        logger.warning(
            "Failed login attempt (identifier=%s, ip=%s)%s",
            identifier,
            client_ip,
            f" - now locked for {lock_status.retry_after_seconds}s" if lock_status.locked else "",
        )
    def _issue_token(self, user: User) -> str:
        """Build and sign the JWT payload for the given user."""
        return create_access_token(
            data={
                "sub": str(user.id),
                "role": user.role.value,
                "username": user.username,
                # Password-version claim: get_current_user rejects any
                # token whose pwd_v doesn't match the user's current
                # password_changed_at, so changing a password immediately
                # invalidates every other token in circulation.
                # Full ISO-8601 (microsecond) string, not a truncated
                # NumericDate — two changes inside the same second must
                # still be distinguishable, or a stale token survives.
                "pwd_v": user.password_changed_at.isoformat(),
            }
        )
