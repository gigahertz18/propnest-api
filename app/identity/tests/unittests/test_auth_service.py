"""
Unit tests for AuthService.login's throttling integration: per-identifier
lockout, per-IP rate limiting, and fail-closed behavior when Redis is
unreachable.

Login-attempt state, IP rate limiting, and the user repo are all mocked
here — the Redis-backed mechanics themselves are covered by
tests/unittests/repositories/test_login_attempt_repository.py and
test_ip_rate_limit_repository.py. These tests only assert AuthService's
*decisions*.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import settings
from app.identity.models.user import UserRole
from app.identity.repositories.login_attempt import LockoutStatus
from app.identity.repositories.ip_rate_limit import RateLimitStatus
from app.identity.services.auth_service import AuthService
from app.core.services.exceptions import (
    AccountLockedError,
    InvalidCredentialsError,
    IpRateLimitExceededError,
    LoginThrottleUnavailableError,
)


def _fake_user(**overrides) -> SimpleNamespace:
    """Minimal duck-typed stand-in — just the fields AuthService.login
    and _issue_token touch, without persisting a real User."""
    defaults = dict(
        id=uuid.uuid4(),
        username="john",
        password_hash="hashed",
        role=UserRole.USER,
        is_active=True,
        password_changed_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def user_repo():
    return AsyncMock()


@pytest.fixture
def login_attempt_repo():
    repo = AsyncMock()
    repo.get_lock_status.return_value = LockoutStatus(locked=False)
    return repo


@pytest.fixture
def ip_rate_limit_repo():
    repo = AsyncMock()
    repo.check.return_value = RateLimitStatus(allowed=True)
    return repo


@pytest.fixture
def service(user_repo, login_attempt_repo, ip_rate_limit_repo):
    return AuthService(
        user_repo=user_repo,
        login_attempt_repo=login_attempt_repo,
        ip_rate_limit_repo=ip_rate_limit_repo,
    )


@pytest.mark.asyncio
class TestLoginLockout:
    async def test_locked_identifier_short_circuits_before_touching_user_repo(
        self, service, user_repo, login_attempt_repo
    ):
        login_attempt_repo.get_lock_status.return_value = LockoutStatus(locked=True, retry_after_seconds=30)

        with pytest.raises(AccountLockedError) as exc_info:
            await service.login(db=AsyncMock(), identifier="john", password="x")

        assert exc_info.value.retry_after_seconds == 30
        user_repo.get_by_identifier.assert_not_called()

    async def test_wrong_password_records_a_failure(self, service, user_repo, login_attempt_repo):
        user_repo.get_by_identifier.return_value = _fake_user()

        with patch("app.identity.services.auth_service.verify_password", return_value=False):
            with pytest.raises(InvalidCredentialsError):
                await service.login(db=AsyncMock(), identifier="john", password="wrong")

        login_attempt_repo.record_failure.assert_awaited_once_with("john")
        login_attempt_repo.record_success.assert_not_called()

    async def test_nonexistent_user_records_a_failure(self, service, user_repo, login_attempt_repo):
        user_repo.get_by_identifier.return_value = None

        with pytest.raises(InvalidCredentialsError):
            await service.login(db=AsyncMock(), identifier="ghost", password="x")

        login_attempt_repo.record_failure.assert_awaited_once_with("ghost")

    async def test_inactive_account_records_a_failure(self, service, user_repo, login_attempt_repo):
        user_repo.get_by_identifier.return_value = _fake_user(is_active=False)

        with patch("app.identity.services.auth_service.verify_password", return_value=True):
            with pytest.raises(InvalidCredentialsError):
                await service.login(db=AsyncMock(), identifier="john", password="x")

        login_attempt_repo.record_failure.assert_awaited_once_with("john")

    async def test_successful_login_clears_lockout_state(self, service, user_repo, login_attempt_repo):
        user_repo.get_by_identifier.return_value = _fake_user()

        with patch("app.identity.services.auth_service.verify_password", return_value=True):
            await service.login(db=AsyncMock(), identifier="john", password="x")

        login_attempt_repo.record_success.assert_awaited_once_with("john")
        login_attempt_repo.record_failure.assert_not_called()

    async def test_client_ip_is_passed_through_for_logging_only(self, service, user_repo, login_attempt_repo):
        """client_ip shouldn't affect lockout keys — it's log-only context."""
        user_repo.get_by_identifier.return_value = _fake_user()

        with patch("app.identity.services.auth_service.verify_password", return_value=True):
            await service.login(db=AsyncMock(), identifier="john", password="x", client_ip="1.2.3.4")

        login_attempt_repo.record_success.assert_awaited_once_with("john")

    async def test_system_scheduler_username_is_rejected_before_any_lookup(
        self, service, user_repo, login_attempt_repo, ip_rate_limit_repo
    ):
        """The system-scheduler identity (see scripts/seed_system_user.py)
        must never authenticate through this endpoint, regardless of
        password. Checked before Redis/DB so a flood of attempts against
        this identifier can't spend rate-limit/lockout budget on an
        account that can never succeed anyway."""
        with pytest.raises(InvalidCredentialsError):
            await service.login(
                db=AsyncMock(),
                identifier=settings.SYSTEM_SCHEDULER_USERNAME,
                password="irrelevant",
                client_ip="1.2.3.4",
            )

        ip_rate_limit_repo.check.assert_not_called()
        login_attempt_repo.get_lock_status.assert_not_called()
        user_repo.get_by_identifier.assert_not_called()


@pytest.mark.asyncio
class TestIpRateLimit:
    async def test_rate_limited_ip_short_circuits_before_lockout_check(
        self, service, login_attempt_repo, ip_rate_limit_repo
    ):
        ip_rate_limit_repo.check.return_value = RateLimitStatus(allowed=False, retry_after_seconds=45)

        with pytest.raises(IpRateLimitExceededError) as exc_info:
            await service.login(db=AsyncMock(), identifier="john", password="x", client_ip="1.2.3.4")

        assert exc_info.value.retry_after_seconds == 45
        login_attempt_repo.get_lock_status.assert_not_called()

    async def test_no_client_ip_skips_the_ip_check(self, service, user_repo, ip_rate_limit_repo):
        user_repo.get_by_identifier.return_value = _fake_user()

        with patch("app.identity.services.auth_service.verify_password", return_value=True):
            await service.login(db=AsyncMock(), identifier="john", password="x", client_ip=None)

        ip_rate_limit_repo.check.assert_not_called()

    async def test_ip_check_runs_with_the_given_ip(self, service, user_repo, ip_rate_limit_repo):
        user_repo.get_by_identifier.return_value = _fake_user()

        with patch("app.identity.services.auth_service.verify_password", return_value=True):
            await service.login(db=AsyncMock(), identifier="john", password="x", client_ip="1.2.3.4")

        ip_rate_limit_repo.check.assert_awaited_once_with("1.2.3.4")


@pytest.mark.asyncio
class TestFailsClosedOnRedisOutage:
    """
    Redis backs both throttling mechanisms. If it's unreachable,
    AuthService.login must reject the attempt rather than silently
    proceed unthrottled — see LoginThrottleUnavailableError.
    """

    async def test_ip_rate_limit_check_failure_fails_closed(self, service, ip_rate_limit_repo):
        ip_rate_limit_repo.check.side_effect = RedisConnectionError("boom")

        with pytest.raises(LoginThrottleUnavailableError):
            await service.login(db=AsyncMock(), identifier="john", password="x", client_ip="1.2.3.4")

    async def test_lockout_check_failure_fails_closed(self, service, login_attempt_repo):
        login_attempt_repo.get_lock_status.side_effect = RedisConnectionError("boom")

        with pytest.raises(LoginThrottleUnavailableError):
            await service.login(db=AsyncMock(), identifier="john", password="x")

    async def test_record_failure_call_failing_fails_closed(self, service, user_repo, login_attempt_repo):
        user_repo.get_by_identifier.return_value = None
        login_attempt_repo.record_failure.side_effect = RedisConnectionError("boom")

        with pytest.raises(LoginThrottleUnavailableError):
            await service.login(db=AsyncMock(), identifier="ghost", password="x")

    async def test_record_success_call_failing_fails_closed(self, service, user_repo, login_attempt_repo):
        user_repo.get_by_identifier.return_value = _fake_user()
        login_attempt_repo.record_success.side_effect = RedisConnectionError("boom")

        with patch("app.identity.services.auth_service.verify_password", return_value=True):
            with pytest.raises(LoginThrottleUnavailableError):
                await service.login(db=AsyncMock(), identifier="john", password="x")


class TestLoginBlocksSystemSchedulerIdentity:
    async def test_system_username_is_rejected_before_touching_user_repo(self, service, user_repo, login_attempt_repo):
        with pytest.raises(InvalidCredentialsError):
            await service.login(db=AsyncMock(), identifier=settings.SYSTEM_SCHEDULER_USERNAME, password="anything")

        user_repo.get_by_identifier.assert_not_called()
        login_attempt_repo.record_failure.assert_not_called()

    async def test_system_email_is_rejected_case_insensitively(self, service, user_repo, login_attempt_repo):
        with pytest.raises(InvalidCredentialsError):
            await service.login(
                db=AsyncMock(),
                identifier=settings.SYSTEM_SCHEDULER_EMAIL.upper(),
                password="anything",
            )

        user_repo.get_by_identifier.assert_not_called()
