"""
Unit tests for the Redis-backed login-attempt/lockout repository.

Runs against the real test Redis instance (settings.REDIS_URL under
UnittestConfig), consistent with how the SQLAlchemy repository tests run
against a real test Postgres DB rather than a mock. The autouse
`_flush_redis` fixture in tests/conftest.py guarantees a clean keyspace
before every test.
"""

import asyncio

import pytest
import pytest_asyncio

import redis.asyncio as redis

from app.core.config import settings
from app.identity.repositories.login_attempt import LoginAttemptRepository


@pytest_asyncio.fixture
async def redis_client():
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def repo(redis_client):
    return LoginAttemptRepository(client=redis_client)


@pytest.mark.asyncio
class TestGetLockStatus:
    async def test_unknown_identifier_is_not_locked(self, repo):
        status = await repo.get_lock_status("nobody")
        assert status.locked is False
        assert status.retry_after_seconds == 0

    async def test_locked_identifier_returns_ttl(self, repo):
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
            await repo.record_failure("john")

        status = await repo.get_lock_status("john")
        assert status.locked is True
        assert 0 < status.retry_after_seconds <= settings.LOGIN_LOCKOUT_BASE_SECONDS

    async def test_lock_status_is_case_and_whitespace_insensitive(self, repo):
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
            await repo.record_failure("John")

        status = await repo.get_lock_status(" john ")
        assert status.locked is True


@pytest.mark.asyncio
class TestRecordFailure:
    async def test_failures_below_threshold_do_not_lock(self, repo):
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS - 1):
            status = await repo.record_failure("john")
            assert status.locked is False

    async def test_reaching_threshold_locks(self, repo):
        status = None
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
            status = await repo.record_failure("john")

        assert status.locked is True
        assert status.retry_after_seconds > 0

    async def test_nonexistent_identifier_locks_the_same_as_a_real_one(self, repo):
        """
        Locking must not depend on whether the identifier corresponds to a
        real account — otherwise a 429-vs-401 difference becomes a way to
        enumerate valid usernames.
        """
        status = None
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
            status = await repo.record_failure("definitely-not-a-real-user")

        assert status.locked is True

    async def test_progressive_backoff_doubles_each_cycle(self, repo):
        first_duration = None
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
            status = await repo.record_failure("john")
        first_duration = status.retry_after_seconds
        assert first_duration == settings.LOGIN_LOCKOUT_BASE_SECONDS

        # Wait out the first lock, then trigger a second lockout cycle.
        await asyncio.sleep(first_duration + 0.5)

        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
            status = await repo.record_failure("john")

        assert status.retry_after_seconds == min(
            settings.LOGIN_LOCKOUT_BASE_SECONDS * 2,
            settings.LOGIN_LOCKOUT_MAX_SECONDS,
        )
        assert status.retry_after_seconds > first_duration


@pytest.mark.asyncio
class TestRecordSuccess:
    async def test_clears_failure_count(self, repo):
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS - 1):
            await repo.record_failure("john")

        await repo.record_success("john")

        # A fresh full run of failures should be needed to lock again —
        # if the old count had survived, this single failure would
        # already be at/over threshold.
        status = await repo.record_failure("john")
        assert status.locked is False

    async def test_clears_an_active_lock(self, repo):
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
            await repo.record_failure("john")
        assert (await repo.get_lock_status("john")).locked is True

        await repo.record_success("john")

        assert (await repo.get_lock_status("john")).locked is False
