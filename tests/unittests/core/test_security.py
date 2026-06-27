from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, verify_password


def test_verify_password_returns_false_for_empty_hash() -> None:
    assert verify_password("password", "") is False


def test_verify_password_returns_false_for_corrupted_hash() -> None:
    assert verify_password("password", "not-a-valid-hash") is False


def test_create_and_decode_access_token_returns_payload_with_correct_aud_iss() -> None:
    token = create_access_token({"sub": "123", "role": "user", "username": "testuser"})
    payload = decode_access_token(token)

    assert payload is not None
    assert payload["sub"] == "123"
    assert payload["iss"] == settings.JWT_ISSUER
    assert payload["aud"] == settings.JWT_AUDIENCE


def test_create_access_token_sets_expiry_in_the_future() -> None:
    """
    Sanity check on the expiry window itself — if someone changes
    ACCESS_TOKEN_EXPIRE_MINUTES or breaks the exp calculation, this should
    catch it independently of the expired-token rejection tests below.
    """
    before = datetime.now(timezone.utc)
    token = create_access_token({"sub": "123", "role": "user", "username": "testuser"})
    payload = decode_access_token(token)

    assert payload is not None
    expected_exp = before + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # Allow a small tolerance for test execution time between `before` and token creation.
    assert abs(payload["exp"] - expected_exp.timestamp()) < 5


def test_decode_access_token_rejects_wrong_issuer() -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "123",
        "role": "user",
        "username": "testuser",
        "exp": now + timedelta(minutes=15),
        "iat": now,
        "iss": "invalid-issuer",
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    assert decode_access_token(token) is None


def test_decode_access_token_rejects_wrong_audience() -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "123",
        "role": "user",
        "username": "testuser",
        "exp": now + timedelta(minutes=15),
        "iat": now,
        "iss": settings.JWT_ISSUER,
        "aud": "invalid-audience",
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    assert decode_access_token(token) is None


def test_decode_access_token_rejects_expired_token() -> None:
    """The most important negative case for a JWT auth system — an
    otherwise perfectly valid token (correct issuer, audience, signature)
    must still be rejected once its `exp` claim is in the past.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "123",
        "role": "user",
        "username": "testuser",
        "exp": now - timedelta(minutes=1),
        "iat": now - timedelta(minutes=16),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    assert decode_access_token(token) is None


def test_decode_access_token_rejects_token_expired_a_long_time_ago() -> None:
    """Distinct from the boundary case above — guards against any future
    refactor that only checks expiry relative to a short window."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "123",
        "role": "user",
        "username": "testuser",
        "exp": now - timedelta(days=30),
        "iat": now - timedelta(days=31),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    assert decode_access_token(token) is None
