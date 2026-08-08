"""
Per-IP request throttling for sensitive, unauthenticated endpoints
(currently just /auth/login).

Backed by the same Redis instance used for login-lockout state, so
throttling is coordinated across every backend worker/instance instead of
being per-process — see the security audit note on
AuthService.login/auth.py's `login` route: the timing-attack mitigation
there had nothing above it limiting request volume.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
)
