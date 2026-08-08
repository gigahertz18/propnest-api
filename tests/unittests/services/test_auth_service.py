"""
Unit tests for AuthService.login's lockout integration.

Login-attempt state and the user repo are both mocked here — the
Redis-backed lockout mechanics themselves are covered by
tests/unittests/repositories/test_login_attempt_repository.py. These
tests only assert AuthService's *decisions*: when it checks the lock,
when it records a failure/success, and what it raises.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.user import UserRole
from app.repositories.login_attempt import LockoutStatus
from app.services.auth_service import AuthService
from app.services.exceptions import AccountLockedError, InvalidCredentialsError


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
def service(user_repo, login_attempt_repo):
    return AuthService(user_repo=user_repo, login_attempt_repo=login_attempt_repo)


@pytest.mark.asyncio
class TestLoginLockout:
    async def test_locked_identifier_short_circuits_before_touching_user_repo(
        self, service, user_repo, login_attempt_repo
    ):
        login_attempt_repo.get_lock_status.return_value = LockoutStatus(
            locked=True, retry_after_seconds=30
        )

        with pytest.raises(AccountLockedError) as exc_info:
            await service.login(db=AsyncMock(), identifier="john", password="x")

        assert exc_info.value.retry_after_seconds == 30
        user_repo.get_by_identifier.assert_not_called()

    async def test_wrong_password_records_a_failure(self, service, user_repo, login_attempt_repo):
        user_repo.get_by_identifier.return_value = _fake_user()

        with patch("app.services.auth_service.verify_password", return_value=False):
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

        with patch("app.services.auth_service.verify_password", return_value=True):
            with pytest.raises(InvalidCredentialsError):
                await service.login(db=AsyncMock(), identifier="john", password="x")

        login_attempt_repo.record_failure.assert_awaited_once_with("john")

    async def test_successful_login_clears_lockout_state(self, service, user_repo, login_attempt_repo):
        user_repo.get_by_identifier.return_value = _fake_user()

        with patch("app.services.auth_service.verify_password", return_value=True):
            await service.login(db=AsyncMock(), identifier="john", password="x")

        login_attempt_repo.record_success.assert_awaited_once_with("john")
        login_attempt_repo.record_failure.assert_not_called()

    async def test_client_ip_is_passed_through_for_logging_only(
        self, service, user_repo, login_attempt_repo
    ):
        """client_ip shouldn't affect lockout keys — it's log-only context."""
        user_repo.get_by_identifier.return_value = _fake_user()

        with patch("app.services.auth_service.verify_password", return_value=True):
            await service.login(db=AsyncMock(), identifier="john", password="x", client_ip="1.2.3.4")

        login_attempt_repo.record_success.assert_awaited_once_with("john")
