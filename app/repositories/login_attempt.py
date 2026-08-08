"""
Redis-backed tracking of failed login attempts and progressive account
lockout.

Keyed on the *normalized identifier* rather than a user id, so counting
and locking behave identically whether or not the identifier corresponds
to a real account. This matters because AuthService.login already
returns the same generic "invalid credentials" error and runs
dummy_verify() for nonexistent users specifically to prevent username
enumeration via timing/response differences — a lockout that only ever
kicks in for real accounts would reopen that exact side channel via a
401-vs-429 split instead.

Lives outside BaseRepository (SQLAlchemy generic CRUD) since this reads
and writes Redis through a completely different client, not Postgres.
"""
from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as redis

from app.core.config import settings


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().lower()


@dataclass
class LockoutStatus:
    locked: bool
    retry_after_seconds: int = 0


class LoginAttemptRepository:
    """
    Redis key layout (all namespaced under `login:`):

    - `login:fail:{identifier}` — failure counter, TTL =
      LOGIN_FAILURE_WINDOW_SECONDS. Deleted on success or on locking.
      Expires on its own if the identifier goes quiet, so a stale failure
      from weeks ago doesn't count toward a fresh lockout.
    - `login:lock:{identifier}` — presence = currently locked out.
      TTL = the lockout duration for the *current* cycle.
    - `login:lockcount:{identifier}` — how many times this identifier has
      recently been locked out. Drives progressive backoff: each new
      lockout roughly doubles the previous duration, capped at
      LOGIN_LOCKOUT_MAX_SECONDS. TTL = LOGIN_LOCKOUT_MAX_SECONDS, so a
      long-quiet identifier eventually decays back to the base delay
      instead of escalating forever.
    """

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    async def get_lock_status(self, identifier: str) -> LockoutStatus:
        norm = _normalize_identifier(identifier)
        ttl = await self._client.ttl(self._lock_key(norm))
        if ttl and ttl > 0:
            return LockoutStatus(locked=True, retry_after_seconds=ttl)
        return LockoutStatus(locked=False)

    async def record_success(self, identifier: str) -> None:
        """Clears the failure count and any active lock for this identifier."""
        norm = _normalize_identifier(identifier)
        await self._client.delete(self._fail_key(norm), self._lock_key(norm))

    async def record_failure(self, identifier: str) -> LockoutStatus:
        """
        Increments the failure counter and locks the identifier out once
        it reaches LOGIN_MAX_FAILED_ATTEMPTS. Returns the resulting lock
        status so the caller can surface a Retry-After to the client.
        """
        norm = _normalize_identifier(identifier)
        fail_key = self._fail_key(norm)

        count = await self._client.incr(fail_key)
        if count == 1:
            await self._client.expire(fail_key, settings.LOGIN_FAILURE_WINDOW_SECONDS)

        if count < settings.LOGIN_MAX_FAILED_ATTEMPTS:
            return LockoutStatus(locked=False)

        return await self._lock(norm)

    # ─── Private ──────────────────────────────────────────
    async def _lock(self, normalized_identifier: str) -> LockoutStatus:
        lockcount_key = self._lockcount_key(normalized_identifier)
        cycle = await self._client.incr(lockcount_key)
        await self._client.expire(lockcount_key, settings.LOGIN_LOCKOUT_MAX_SECONDS)

        duration = min(
            settings.LOGIN_LOCKOUT_BASE_SECONDS * (2 ** (cycle - 1)),
            settings.LOGIN_LOCKOUT_MAX_SECONDS,
        )

        await self._client.set(self._lock_key(normalized_identifier), "1", ex=duration)
        # The lock itself is now the throttle — clear the failure counter
        # so that once the lock expires, the identifier gets a fresh set
        # of attempts rather than an immediate re-lock from leftover count.
        await self._client.delete(self._fail_key(normalized_identifier))

        return LockoutStatus(locked=True, retry_after_seconds=duration)

    def _fail_key(self, normalized_identifier: str) -> str:
        return f"login:fail:{normalized_identifier}"

    def _lock_key(self, normalized_identifier: str) -> str:
        return f"login:lock:{normalized_identifier}"

    def _lockcount_key(self, normalized_identifier: str) -> str:
        return f"login:lockcount:{normalized_identifier}"
