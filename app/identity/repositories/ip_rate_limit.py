"""
Redis-backed per-IP request rate limiting for /auth/login.

Async-native by design. slowapi's Redis storage backend wraps `limits`'
synchronous RedisStorage — every request would make a blocking, sync
network call to Redis from inside the async event loop, stalling the
entire worker (not just that request) for the round trip. That's a real
concern in the critical path of the busiest unauthenticated endpoint in
the app, so this hand-rolls a small async-native check instead of using
slowapi's Redis integration.

Uses a fixed-window counter: INCR the per-IP key, set its TTL only on
the first hit in the window. Same approach LoginAttemptRepository uses
for its failure counter — kept consistent rather than reaching for a
different algorithm (e.g. sliding window) for a check this coarse.
"""

from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as redis


@dataclass
class RateLimitStatus:
    allowed: bool
    retry_after_seconds: int = 0


class IpRateLimitRepository:
    def __init__(self, client: redis.Redis, limit: int, window_seconds: int) -> None:
        self._client = client
        self._limit = limit
        self._window_seconds = window_seconds

    async def check(self, ip: str) -> RateLimitStatus:
        """
        Increments this IP's request count for the current window and
        reports whether it's still within the configured limit.
        """
        key = self._key(ip)
        count = await self._client.incr(key)
        if count == 1:
            await self._client.expire(key, self._window_seconds)

        if count <= self._limit:
            return RateLimitStatus(allowed=True)

        ttl = await self._client.ttl(key)
        # ttl can come back -1 in a narrow race right after incr but
        # before expire on the very first hit — 1s is a safe floor
        # rather than surfacing a nonsensical negative Retry-After.
        return RateLimitStatus(allowed=False, retry_after_seconds=max(ttl, 1))

    def _key(self, ip: str) -> str:
        return f"ratelimit:login:{ip}"
