"""
Shared async Redis client for rate limiting and login-lockout state.

A single client is created lazily and reused for the process lifetime —
redis-py's async client manages its own internal connection pool and is
safe for concurrent use, so unlike `get_db()` there's no need to open a
new connection per request.
"""
import redis.asyncio as redis

from app.core.config import settings

_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """
    Returns the process-wide async Redis client, creating it on first use.

    FastAPI dependency — inject with `Depends(get_redis_client)` wherever
    Redis-backed state (rate limiting, login lockout) is needed. Tests can
    override this dependency if they ever need to isolate it further.
    """
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


async def close_redis_client() -> None:
    """Closes the shared client. Called from the app lifespan on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
