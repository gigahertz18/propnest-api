"""
Unit tests for the Redis-backed per-IP rate limit repository.

Runs against the real test Redis instance, same as
test_login_attempt_repository.py — see that file's docstring for why.
"""

import pytest
import pytest_asyncio

import redis.asyncio as redis

from app.core.config import settings
from app.identity.repositories.ip_rate_limit import IpRateLimitRepository


@pytest_asyncio.fixture
async def redis_client():
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def repo(redis_client):
    return IpRateLimitRepository(client=redis_client, limit=3, window_seconds=60)


@pytest.mark.asyncio
class TestIpRateLimit:
    async def test_requests_within_limit_are_allowed(self, repo):
        for _ in range(3):
            status = await repo.check("1.2.3.4")
            assert status.allowed is True

    async def test_request_over_limit_is_denied(self, repo):
        for _ in range(3):
            await repo.check("1.2.3.4")

        status = await repo.check("1.2.3.4")
        assert status.allowed is False
        assert status.retry_after_seconds > 0

    async def test_different_ips_have_independent_counters(self, repo):
        for _ in range(3):
            await repo.check("1.2.3.4")

        # A different IP shouldn't be affected by the first one's count.
        status = await repo.check("5.6.7.8")
        assert status.allowed is True

    async def test_window_resets_after_ttl(self, repo):
        short_window_repo = IpRateLimitRepository(client=repo._client, limit=1, window_seconds=1)

        first = await short_window_repo.check("9.9.9.9")
        assert first.allowed is True

        second = await short_window_repo.check("9.9.9.9")
        assert second.allowed is False

        import asyncio

        await asyncio.sleep(1.2)

        third = await short_window_repo.check("9.9.9.9")
        assert third.allowed is True
