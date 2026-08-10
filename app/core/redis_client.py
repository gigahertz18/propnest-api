"""
Owns the lifecycle of a single async Redis client used for rate limiting
and login-lockout state.

Deliberately holds no module-level state — construction and teardown
belong to whoever creates an instance, not to this module:

- In production, main.py's lifespan creates exactly one
  `RedisClientManager` at startup and stores it on `app.state.redis`,
  closing it at shutdown. One instance, one event loop, for the life of
  the app.
- In tests, a fixture creates a *fresh* `RedisClientManager` per test
  function.

That per-owner lifetime is what actually solves the cross-event-loop
problem an async Redis client runs into under pytest-asyncio: each test
function gets its own event loop (see pytest.ini's
asyncio_default_fixture_loop_scope = function), and an async client's
connection pool is bound to whichever loop was running when it was first
used. A process-wide singleton would get reused across different tests'
loops and crash on the second one. A fresh manager per test avoids that
with no test-specific branching inside this class at all.
"""

import redis.asyncio as redis


class RedisClientManager:
    """
    Creates a Redis client on first use and reuses it until closed.

    Connection pooling and timeouts are tuned the same way the SQLAlchemy
    engine is tuned for production (see app/db/session.py's pool_size /
    pool_pre_ping): an unbounded pool with no socket timeout means a
    Redis hang or a burst of concurrent requests can either exhaust
    connections or hang requests indefinitely — and since AuthService.login
    awaits Redis before anything else, a hang here hangs every login
    attempt.
    """

    def __init__(
        self,
        url: str,
        max_connections: int = 20,
        socket_timeout: float = 2.0,
        socket_connect_timeout: float = 2.0,
        health_check_interval: int = 30,
    ) -> None:
        self._url = url
        self._max_connections = max_connections
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout
        self._health_check_interval = health_check_interval
        self._client: redis.Redis | None = None

    def get_client(self) -> redis.Redis:
        """Returns the managed client, creating it on first use."""
        if self._client is None:
            self._client = redis.from_url(
                self._url,
                decode_responses=True,
                max_connections=self._max_connections,
                socket_timeout=self._socket_timeout,
                socket_connect_timeout=self._socket_connect_timeout,
                health_check_interval=self._health_check_interval,
            )
        return self._client

    async def close(self) -> None:
        """Closes the managed client, if one was ever created. Safe to call more than once."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
