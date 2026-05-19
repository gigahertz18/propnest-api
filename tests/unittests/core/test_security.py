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


def test_decode_access_token_rejects_wrong_issuer() -> None:
    payload = {
        "sub": "123",
        "role": "user",
        "username": "testuser",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "iat": datetime.now(timezone.utc),
        "iss": "invalid-issuer",
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    assert decode_access_token(token) is None


def test_decode_access_token_rejects_wrong_audience() -> None:
    payload = {
        "sub": "123",
        "role": "user",
        "username": "testuser",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "iat": datetime.now(timezone.utc),
        "iss": settings.JWT_ISSUER,
        "aud": "invalid-audience",
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    assert decode_access_token(token) is None
