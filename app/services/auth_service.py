import logging

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import verify_password, create_access_token
from app.repositories.user import UserRepository
from app.repositories.login_attempt import LoginAttemptRepository, LockoutStatus
from app.repositories.ip_rate_limit import IpRateLimitRepository
from app.schemas.user import TokenResponse, UserResponse
from app.models.user import User
from app.services.exceptions import (
    AccountLockedError,
    InvalidCredentialsError,
    IpRateLimitExceededError,
    LoginThrottleUnavailableError,
)

logger = logging.getLogger(__name__)


class AuthService:
    """
    Handles all authentication business logic.

    Responsibilities:
    - Validating credentials
    - Checking account state
    - Throttling repeated failures per identifier (progressive lockout)
    - Throttling request volume per source IP
    - Generating JWT tokens

    Raises domain exceptions (not HTTP exceptions) —
    the route layer is responsible for converting these to HTTP responses.

    Fails closed on Redis errors: if either throttling mechanism is
    unreachable, login is rejected rather than silently proceeding
    unthrottled — see LoginThrottleUnavailableError.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        login_attempt_repo: LoginAttemptRepository,
        ip_rate_limit_repo: IpRateLimitRepository,
    ) -> None:
        self.user_repo = user_repo
        self.login_attempt_repo = login_attempt_repo
        self.ip_rate_limit_repo = ip_rate_limit_repo

    async def login(
        self,
        db: AsyncSession,
        identifier: str,
        password: str,
        client_ip: str | None = None,
    ) -> TokenResponse:
        """
        Authenticate a user by username or email + password.

        Two independent Redis-backed throttles sit above credential
        checking: a per-IP request rate limit (coarse — catches one
        source spraying many identifiers) and a per-identifier
        progressive lockout (fine — catches repeated guesses against one
        account regardless of source). Both fail closed: if Redis is
        unreachable, login is rejected rather than silently skipping
        throttling.

        Raises:
            IpRateLimitExceededError: if this IP has made too many
                requests in the current window.
            AccountLockedError: if the identifier has too many recent
                failures and is inside an active lockout window.
            InvalidCredentialsError: if identifier not found or password is wrong.
            LoginThrottleUnavailableError: if Redis is unreachable.

        Returns:
            TokenResponse with a signed JWT access token.
        """
        # The system-scheduler identity authenticates only via a direct
        # repo lookup by id from the ARQ job — never through this
        # endpoint. Checked first, before either Redis-backed throttle,
        # so attempts against this identifier don't spend rate-limit/
        # lockout budget on an account that can never log in. Same
        # InvalidCredentialsError as any other failure — doesn't reveal
        # that this identifier is special. Email compared case-insensitively
        # to match how every other email lookup in this codebase treats it.
        if identifier == settings.SYSTEM_SCHEDULER_USERNAME or (
            identifier.casefold() == settings.SYSTEM_SCHEDULER_EMAIL.casefold()
        ):
            raise InvalidCredentialsError("The identifier or password you entered is incorrect.")

        if client_ip:
            await self._check_ip_rate_limit(client_ip)

        lock_status = await self._check_lock_status(identifier)
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

        await self._record_success(identifier)
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
    async def _check_ip_rate_limit(self, client_ip: str) -> None:
        try:
            status = await self.ip_rate_limit_repo.check(client_ip)
        except RedisError as e:
            logger.error("Redis unavailable while checking IP rate limit (ip=%s): %s", client_ip, e)
            raise LoginThrottleUnavailableError() from e

        if not status.allowed:
            logger.warning(
                "Login blocked — IP rate limit exceeded (ip=%s, retry_after=%ss)",
                client_ip,
                status.retry_after_seconds,
            )
            raise IpRateLimitExceededError(status.retry_after_seconds)

    async def _check_lock_status(self, identifier: str) -> LockoutStatus:
        try:
            return await self.login_attempt_repo.get_lock_status(identifier)
        except RedisError as e:
            logger.error("Redis unavailable while checking login lockout status (identifier=%s): %s", identifier, e)
            raise LoginThrottleUnavailableError() from e

    async def _record_failure(self, identifier: str, client_ip: str | None) -> None:
        try:
            lock_status = await self.login_attempt_repo.record_failure(identifier)
        except RedisError as e:
            logger.error("Redis unavailable while recording failed login (identifier=%s): %s", identifier, e)
            raise LoginThrottleUnavailableError() from e

        logger.warning(
            "Failed login attempt (identifier=%s, ip=%s)%s",
            identifier,
            client_ip,
            f" — now locked for {lock_status.retry_after_seconds}s" if lock_status.locked else "",
        )

    async def _record_success(self, identifier: str) -> None:
        try:
            await self.login_attempt_repo.record_success(identifier)
        except RedisError as e:
            logger.error("Redis unavailable while clearing login lockout state (identifier=%s): %s", identifier, e)
            raise LoginThrottleUnavailableError() from e

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
